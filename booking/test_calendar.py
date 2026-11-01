"""Server contracts shared by the enhanced calendar and no-JavaScript form."""
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import Appointment, DayOff
from .rules import SOFIA
from .test_filtering import FilterHTML
from .tests import BookingFixtures, NOW


class CalendarHTML(FilterHTML):
    def __init__(self, response):
        self.elements = {}
        super().__init__(response)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.elements[attributes["id"]] = attributes
        super().handle_starttag(tag, attrs)


class DateCalendarTests(BookingFixtures, TestCase):
    def get_calendar(self, **values):
        response = self.client.get(reverse("booking:book"), {"lang": "en", **values})
        self.assertEqual(response.status_code, 200)
        return response, CalendarHTML(response)

    def test_unselected_calendar_keeps_visible_labelled_select_fallback(self):
        response, html = self.get_calendar()
        self.assertNotIn("hidden", html.elements["id_date"])
        self.assertIn("hidden", html.elements["date-calendar"])
        self.assertContains(response, '<label for="id_date">Date:</label>', html=True)
        self.assertIn("selected", html.selects["date"][""])
        self.assertFalse(any("selected" in option for value, option in html.selects["date"].items() if value))
        self.assertEqual(set(html.get_fields), {"service", "barber", "date", "lang"})
        self.assertIsNone(response.context["form"])

    def test_calendar_bounds_cover_exact_sofia_window_across_year_and_leap_day(self):
        clocks = (
            datetime(2030, 12, 20, 9, tzinfo=SOFIA),
            datetime(2032, 2, 15, 9, tzinfo=SOFIA),
            # Sofia has crossed New Year although UTC is still December 31.
            datetime(2030, 12, 31, 22, 30, tzinfo=datetime_timezone.utc),
        )
        for clock in clocks:
            with self.subTest(clock=clock), patch("django.utils.timezone.now", return_value=clock):
                _, html = self.get_calendar()
                today = clock.astimezone(SOFIA).date()
                expected = {(today + timedelta(days=offset)).isoformat() for offset in range(29)}
                self.assertEqual(html.elements["id_date"]["data-min-date"], today.isoformat())
                self.assertEqual(html.elements["id_date"]["data-max-date"], (today + timedelta(days=28)).isoformat())
                self.assertEqual(set(html.selects["date"]) - {""}, expected)
                self.assertTrue(all(html.selects["date"][day]["data-available"] == "true" for day in expected))

    def test_date_metadata_obeys_barber_filter_and_marks_closed_dates_disabled(self):
        closed = (NOW.date() + timedelta(days=1)).isoformat()
        DayOff.objects.create(barber=self.barber, date=closed)
        _, all_barbers = self.get_calendar(service=self.service.pk)
        self.assertEqual(all_barbers.selects["date"][closed]["data-available"], "true")
        _, one_barber = self.get_calendar(service=self.service.pk, barber=self.barber.pk)
        closed_option = one_barber.selects["date"][closed]
        self.assertEqual(closed_option["data-available"], "false")
        self.assertIn("disabled", closed_option)
        self.assertEqual(one_barber.selects["date"][NOW.date().isoformat()]["data-available"], "true")

    def test_selected_closed_or_outside_dates_remain_unavailable_even_when_enabled(self):
        closed = NOW.date() + timedelta(days=1)
        DayOff.objects.create(barber=self.barber, date=closed)
        values = (closed.isoformat(), (NOW.date() - timedelta(days=1)).isoformat(),
                  (NOW.date() + timedelta(days=29)).isoformat(), "not-a-date")
        for value in values:
            with self.subTest(date=value):
                response, html = self.get_calendar(service=self.service.pk, barber=self.barber.pk, date=value)
                option = html.selects["date"][value]
                self.assertIn("selected", option)
                self.assertNotIn("disabled", option)  # Apply must preserve stale selections.
                self.assertEqual(option["data-available"], "false")
                self.assertTrue(response.context["no_matches"])
                self.assertContains(response, "Your selections have been kept.")
                self.assertFalse(response.context["slots"])
                self.assertIsNone(response.context["form"])
                self.assertEqual(html.elements["id_date"]["data-min-date"], NOW.date().isoformat())
                self.assertEqual(html.elements["id_date"]["data-max-date"], (NOW.date() + timedelta(days=28)).isoformat())

    def test_availability_metadata_is_language_independent_and_feedback_is_translated(self):
        closed = NOW.date() + timedelta(days=1)
        DayOff.objects.create(barber=self.barber, date=closed)
        metadata = []
        for language, unavailable, previous, recovery in (
            ("en", "unavailable", "Previous month", "Your selections have been kept."),
            ("bg", "няма свободни часове", "Предишен месец", "Изборите Ви са запазени."),
        ):
            response, html = self.get_calendar(lang=language, barber=self.barber.pk, date=closed.isoformat())
            metadata.append({value: option.get("data-available") for value, option in html.selects["date"].items()})
            self.assertEqual(html.elements["date-calendar"]["data-unavailable"], unavailable)
            self.assertIn(unavailable, html.selects["date"][closed.isoformat()]["text"])
            self.assertContains(response, f'aria-label="{previous}"')
            self.assertContains(response, recovery)
        self.assertEqual(metadata[0], metadata[1])

    def test_post_cannot_book_closed_or_outside_calendar_dates(self):
        payload = self.booking_payload()
        closed = NOW.date() + timedelta(days=1)
        DayOff.objects.create(barber=self.barber, date=closed)
        for day in (closed, NOW.date() - timedelta(days=1), NOW.date() + timedelta(days=29)):
            with self.subTest(day=day):
                response = self.client.post(reverse("booking:book"), {**payload, "date": day.isoformat()})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].non_field_errors())
                self.assertFalse(response.context["slots"])
                self.assertEqual(CalendarHTML(response).selects["date"][day.isoformat()]["data-available"], "false")
        self.assertFalse(Appointment.objects.exists())
