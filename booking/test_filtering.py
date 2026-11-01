"""Public filtering contracts, using synthetic schedules and a fixed Sofia clock."""
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from html.parser import HTMLParser
from itertools import permutations
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalogue.models import Service
from .models import Appointment, DayOff, WorkingHours
from .rules import available_slots
from .tests import BookingFixtures, NOW


class FilterHTML(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.selects, self.links, self.get_fields = {}, [], []
        self.select = self.option = None
        self.in_get = False
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_get = attrs.get("method", "get") == "get"
        if self.in_get and tag in ("input", "select") and attrs.get("name"):
            self.get_fields.append(attrs["name"])
        if tag == "select":
            self.select = attrs["name"]
            self.selects[self.select] = {}
        if tag == "option" and self.select:
            self.option = {**attrs, "text": ""}
            self.selects[self.select][attrs.get("value", "")] = self.option
        if tag == "a":
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None
        elif tag == "option":
            self.option = None
        elif tag == "form":
            self.in_get = False

    def handle_data(self, data):
        if self.option is not None:
            self.option["text"] += data

    def available(self, field):
        return {
            value for value, option in self.selects[field].items()
            if value and "disabled" not in option and "unavailable" not in option["text"]
        }


class BookingFilterTests(BookingFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.long = Service.objects.create(name="Synthetic long service", duration_minutes=60, price="35.00")
        self.barber.services.add(self.long)
        WorkingHours.objects.all().delete()
        for weekday, closes in ((0, time(10, 45)), (1, time(12)), (2, time(10, 30)), (3, time(11))):
            WorkingHours.objects.create(barber=self.barber, weekday=weekday, opens_at=time(10), closes_at=closes)
        WorkingHours.objects.create(barber=self.other, weekday=0, opens_at=time(11), closes_at=time(12))
        self.day_off = NOW.date() + timedelta(days=3)
        DayOff.objects.create(barber=self.barber, date=self.day_off)
        self.booked_day = NOW.date() + timedelta(days=2)
        self.appointment = self.reserve(day=self.booked_day)
        self.complete = {"service": str(self.long.pk), "barber": str(self.barber.pk), "date": (NOW.date() + timedelta(days=1)).isoformat()}

    def get_filters(self, **values):
        response = self.client.get(reverse("booking:book"), {"lang": "en", **values})
        self.assertEqual(response.status_code, 200)
        return response, FilterHTML(response)

    def assert_preserved(self, html, values):
        for field in ("service", "barber", "date"):
            selected = [value for value, option in html.selects[field].items() if "selected" in option]
            self.assertEqual(selected, [str(values.get(field, ""))], field)

    def test_blank_filters_have_no_defaults_errors_times_or_details(self):
        response, html = self.get_filters()
        self.assert_preserved(html, {})
        self.assertFalse(response.context["selection"].errors)
        self.assertFalse(response.context["slots"])
        self.assertIsNone(response.context["form"])
        self.assertNotContains(response, 'id="details"')
        self.assertEqual(html.available("service"), {str(self.service.pk), str(self.long.pk)})
        self.assertEqual(html.available("barber"), {str(self.barber.pk), str(self.other.pk)})

    def test_all_six_orders_preserve_choices_and_offer_the_next_valid_choice(self):
        for order in permutations(self.complete):
            with self.subTest(order=order):
                values = {}
                for field in order:
                    _, before = self.get_filters(**values)
                    self.assertIn(self.complete[field], before.available(field))
                    values[field] = self.complete[field]
                    response, html = self.get_filters(**values)
                    self.assert_preserved(html, values)
                    self.assertFalse(response.context["selection"].errors)
                    self.assertEqual(bool(response.context["slots"]), len(values) == 3)
                    self.assertIsNone(response.context["form"])
                response, _ = self.get_filters(**values, time="10:00")
                self.assertContains(response, 'id="details"')

    def test_each_choice_uses_other_two_filters_and_actual_duration(self):
        _, html = self.get_filters(date=NOW.date().isoformat())
        self.assertEqual(html.available("service"), {str(self.service.pk)})
        self.assertEqual(html.available("barber"), {str(self.barber.pk), str(self.other.pk)})
        _, html = self.get_filters(barber=self.other.pk)
        self.assertEqual(html.available("service"), {str(self.service.pk)})
        _, html = self.get_filters(service=self.long.pk)
        self.assertEqual(html.available("barber"), {str(self.barber.pk)})
        self.assertNotIn(NOW.date().isoformat(), html.available("date"))
        _, html = self.get_filters(**self.complete)
        self.assertEqual(html.available("service"), {str(self.service.pk), str(self.long.pk)})

    def test_dates_include_disabled_day_off_booked_and_closed_days(self):
        _, html = self.get_filters(barber=self.barber.pk, service=self.service.pk)
        dates = html.selects["date"]
        self.assertEqual(len(dates), 30)  # blank plus the inclusive 29-day horizon.
        for day in (self.day_off, self.booked_day, NOW.date() + timedelta(days=4)):
            with self.subTest(day=day):
                self.assertIn("disabled", dates[day.isoformat()])
                self.assertIn("unavailable", dates[day.isoformat()]["text"])
        self.assertIn((NOW.date() + timedelta(days=28)).isoformat(), html.available("date"))

    def test_cancellation_releases_date_without_disclosing_customer_data(self):
        response, html = self.get_filters(barber=self.barber.pk)
        self.assertNotIn(self.booked_day.isoformat(), html.available("date"))
        for value in (self.appointment.customer_name, self.appointment.phone, self.appointment.email, str(self.appointment.reference)):
            self.assertNotContains(response, value)
        self.appointment.cancelled_at = NOW
        self.appointment.save(update_fields=["cancelled_at"])
        _, html = self.get_filters(barber=self.barber.pk)
        self.assertIn(self.booked_day.isoformat(), html.available("date"))

    def test_inactive_services_barbers_and_login_accounts_are_not_offered(self):
        self.long.is_active = False
        self.long.save()
        self.other.user.is_active = False
        self.other.user.save()
        _, html = self.get_filters()
        self.assertEqual(html.available("service"), {str(self.service.pk)})
        self.assertEqual(html.available("barber"), {str(self.barber.pk)})
        self.barber.is_active = False
        self.barber.save()
        response, html = self.get_filters()
        self.assertFalse(html.available("service"))
        self.assertFalse(html.available("barber"))
        self.assertTrue(response.context["no_matches"])

    def test_horizon_uses_sofia_day_and_today_requires_strictly_future_slot(self):
        # At 10:15 the short shift has no strictly future 30-minute start.
        with patch("django.utils.timezone.now", return_value=NOW.replace(hour=10, minute=15)):
            _, html = self.get_filters(barber=self.barber.pk)
            self.assertNotIn(NOW.date().isoformat(), html.available("date"))
        midnight = datetime(2030, 1, 7, 22, 30, tzinfo=datetime_timezone.utc)
        with patch("django.utils.timezone.now", return_value=midnight):
            _, html = self.get_filters()
            dates = html.selects["date"]
            self.assertNotIn(NOW.date().isoformat(), dates)
            self.assertIn((NOW.date() + timedelta(days=29)).isoformat(), dates)

    def test_stale_incompatible_and_malformed_values_are_retained_with_recovery(self):
        cases = [
            {**self.complete, "barber": str(self.other.pk)},
            {**self.complete, "date": self.day_off.isoformat()},
            {"service": "999999"}, {"barber": "not-a-number"},
            {"date": "not-a-date"}, {"date": "2030-01-06"}, {"date": "2030-02-05"},
        ]
        for values in cases:
            with self.subTest(values=values):
                response, html = self.get_filters(**values)
                self.assert_preserved(html, values)
                self.assertTrue(response.context["no_matches"])
                self.assertFalse(response.context["slots"])
                self.assertIsNone(response.context["form"])
                self.assertContains(response, "Your selections have been kept.")
                for field, value in values.items():
                    self.assertIn("unavailable", html.selects[field][value]["text"])
                    self.assertNotIn("disabled", html.selects[field][value])

    def test_deactivated_selection_is_kept_and_clear_recovers(self):
        self.long.is_active = False
        self.long.save()
        response, html = self.get_filters(**self.complete)
        self.assert_preserved(html, self.complete)
        self.assertContains(response, "unavailable")
        clear = next(link for link in html.links if link.get("aria-label") == "Clear Service")
        response = self.client.get(reverse("booking:book") + clear["href"])
        self.assert_preserved(FilterHTML(response), {key: value for key, value in self.complete.items() if key != "service"})
        self.assertFalse(response.context["no_matches"])

    def test_clear_and_reset_preserve_language_and_clear_old_time_without_javascript(self):
        for language, prefix in (("en", "Clear"), ("bg", "Изчисти")):
            response, html = self.get_filters(**self.complete, time="10:00", lang=language)
            self.assertEqual(set(html.get_fields), {"service", "barber", "date", "lang"})
            clears = [link for link in html.links if link.get("aria-label", "").startswith(prefix + " ")]
            self.assertEqual(len(clears), 3)
            for link in clears:
                query = parse_qs(urlsplit(link["href"]).query)
                self.assertEqual(query.pop("lang"), [language])
                self.assertEqual(len(query), 2)
                for field, value in query.items():
                    self.assertEqual(value, [self.complete[field]])
                cleared = self.client.get(reverse("booking:book") + link["href"])
                self.assert_preserved(FilterHTML(cleared), {key: value[0] for key, value in query.items()})
                self.assertIsNone(cleared.context["form"])
            reset_url = reverse("booking:book") + f"?lang={language}#visit-selection"
            self.assertTrue(any(link.get("href") == reset_url for link in html.links))
            reset = self.client.get(reset_url)
            self.assertContains(reset, f'<html lang="{language}">')
            self.assert_preserved(FilterHTML(reset), {})

    def test_partial_get_ignores_time_but_post_requires_all_three_filters(self):
        response, _ = self.get_filters(service=self.service.pk, time="10:00")
        self.assertFalse(response.context["selection"].errors)
        self.assertIsNone(response.context["form"])
        payload = self.booking_payload(**self.complete)
        for field in self.complete:
            with self.subTest(field=field):
                invalid = self.client.post(reverse("booking:book"), {**payload, field: ""})
                self.assertIn(field, invalid.context["form"].errors)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_stale_get_time_and_hostile_filter_values_have_safe_bilingual_feedback(self):
        for language, recovery in (("en", "Your selections have been kept."), ("bg", "Изборите Ви са запазени.")):
            response, html = self.get_filters(**self.complete, time="10:07", lang=language)
            self.assert_preserved(html, self.complete)
            self.assertTrue(response.context["selection"].non_field_errors())
            self.assertIsNone(response.context["form"])
            hostile = '<script>alert("synthetic")</script>'
            response, html = self.get_filters(service=hostile, lang=language)
            self.assert_preserved(html, {"service": hostile})
            self.assertContains(response, recovery)
            self.assertNotContains(response, hostile)
            self.assertNotContains(response, 'id="details"')

    def test_stale_time_is_rejected_after_another_customer_reserves(self):
        payload = self.booking_payload(**self.complete)
        self.reserve(service_id=self.long.pk, day=NOW.date() + timedelta(days=1))
        response = self.client.post(reverse("booking:book"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertEqual(Appointment.objects.count(), 2)
        self.assertNotIn(time(10), [slot.time() for slot in response.context["slots"]])

    def test_public_full_selection_slots_match_transactional_availability(self):
        for service, barber, offset in (
            (self.service, self.barber, 0), (self.long, self.barber, 0),
            (self.long, self.barber, 1), (self.service, self.barber, 2),
            (self.service, self.barber, 3), (self.service, self.other, 0),
            (self.long, self.other, 0), (self.service, self.barber, 28),
        ):
            day = NOW.date() + timedelta(days=offset)
            with self.subTest(service=service.pk, barber=barber.pk, day=day):
                response, _ = self.get_filters(service=service.pk, barber=barber.pk, date=day.isoformat())
                self.assertEqual(response.context["slots"], available_slots(barber, service, day))

    def test_filters_share_exact_duration_rounding_and_strict_now_rules(self):
        self.service.duration_minutes = 35
        self.service.save()
        WorkingHours.objects.filter(barber=self.barber, weekday=0).update(opens_at=time(10, 1), closes_at=time(11))
        values = {"service": self.service.pk, "barber": self.barber.pk, "date": NOW.date().isoformat()}
        response, _ = self.get_filters(**values)
        self.assertEqual([slot.time() for slot in response.context["slots"]], [time(10, 15)])
        with patch("django.utils.timezone.now", return_value=NOW.replace(hour=10, minute=15)):
            response, html = self.get_filters(**values)
            self.assertFalse(response.context["slots"])
            self.assertIn("unavailable", html.selects["date"][values["date"]]["text"])

    def test_filter_queries_do_not_grow_per_barber_service_or_date(self):
        self.get_filters()  # Establish the session before measuring.
        with CaptureQueriesContext(connection) as baseline:
            self.get_filters()
        for index in range(4):
            extra = self.make_barber(f"synthetic-extra-{index}")
            extra_service = Service.objects.create(name=f"Synthetic extra {index}", duration_minutes=30, price="10.00")
            extra.services.add(self.long, extra_service)
        with CaptureQueriesContext(connection) as expanded:
            response, _ = self.get_filters()
        self.assertLessEqual(len(expanded), len(baseline) + 1)
        self.assertLessEqual(len(expanded), 12)
        self.assertFalse(response.context["no_matches"])
