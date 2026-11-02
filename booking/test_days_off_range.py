"""Inclusive leave ranges, atomic conflicts, and staff/public integration."""
from datetime import date, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from .forms import DayOffForm
from .models import DayOff
from .rules import add_days_off, cancel_appointment
from .tests import BookingFixtures, NOW


class DayOffRangeTests(BookingFixtures, TestCase):
    def days_off(self, barber=None):
        return set(DayOff.objects.filter(barber=barber or self.barber).values_list("date", flat=True))

    def hours_url(self, barber=None):
        return reverse("booking:hours", args=[(barber or self.barber).pk])

    def test_three_day_range_includes_both_endpoints_and_is_idempotent(self):
        start = NOW.date()
        middle, end = start + timedelta(days=1), start + timedelta(days=2)
        existing = DayOff.objects.create(barber=self.barber, date=middle)
        add_days_off(self.barber.pk, start, end)
        add_days_off(self.barber.pk, middle, end)
        self.assertEqual(self.days_off(), {start, middle, end})
        self.assertTrue(DayOff.objects.filter(pk=existing.pk, date=middle).exists())
        self.assertEqual(DayOff.objects.count(), 3)
        self.assertFalse(self.days_off(self.other))

    def test_blank_or_equal_end_adds_only_one_day(self):
        self.client.force_login(self.barber.user)
        for offset, end in ((0, ""), (1, None)):
            start = NOW.date() + timedelta(days=offset)
            with self.subTest(end=end):
                response = self.client.post(self.hours_url(), {
                    "action": "add_off", "date": start.isoformat(),
                    "end_date": start.isoformat() if end is None else end,
                })
                self.assertRedirects(response, self.hours_url())
        add_days_off(self.barber.pk, NOW.date() + timedelta(days=2))
        self.assertEqual(self.days_off(), {NOW.date() + timedelta(days=n) for n in range(3)})

    def test_month_year_and_leap_boundaries(self):
        ranges = (
            (date(2030, 1, 31), date(2030, 2, 2)),
            (date(2030, 12, 31), date(2031, 1, 2)),
            (date(2032, 2, 28), date(2032, 3, 1)),
        )
        expected = set()
        for start, end in ranges:
            with self.subTest(start=start):
                add_days_off(self.barber.pk, start, end)
                expected.update(start + timedelta(days=n) for n in range(3))
                self.assertEqual(self.days_off(), expected)
        self.assertIn(date(2032, 2, 29), self.days_off())

    def test_maximum_366_days_is_inclusive(self):
        start = NOW.date()
        add_days_off(self.barber.pk, start, start + timedelta(days=365))
        self.assertEqual(len(self.days_off()), 366)
        self.assertIn(start + timedelta(days=365), self.days_off())
        self.assertNotIn(start + timedelta(days=366), self.days_off())

    def test_invalid_direct_ranges_do_not_change_existing_days(self):
        start = NOW.date()
        existing = DayOff.objects.create(barber=self.barber, date=start - timedelta(days=1))
        for first, last in (
            (start, start - timedelta(days=1)),
            (start, start + timedelta(days=366)),
            (start, "invalid"), (None, start), (NOW, start),
        ):
            with self.subTest(start=first, end=last), self.assertRaises(ValidationError):
                add_days_off(self.barber.pk, first, last)
            self.assertEqual(list(DayOff.objects.values_list("pk", flat=True)), [existing.pk])

    def test_invalid_posted_ranges_report_errors_without_writes(self):
        self.client.force_login(self.owner)
        start = NOW.date()
        for first, last, error_field in (
            (start.isoformat(), "not-a-date", "end_date"),
            (start.isoformat(), "2030-02-30", "end_date"),
            ("", start.isoformat(), "date"),
            ("not-a-date", start.isoformat(), "date"),
            (start.isoformat(), (start - timedelta(days=1)).isoformat(), "__all__"),
            (start.isoformat(), (start + timedelta(days=366)).isoformat(), "__all__"),
        ):
            with self.subTest(start=first, end=last):
                response = self.client.post(self.hours_url(), {
                    "action": "add_off", "date": first, "end_date": last,
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn(error_field, response.context["off_form"].errors)
                self.assertFalse(DayOff.objects.exists())

    def test_future_middle_and_end_conflicts_reject_entire_range(self):
        start, end = NOW.date(), NOW.date() + timedelta(days=2)
        existing = DayOff.objects.create(barber=self.barber, date=start - timedelta(days=1))
        for offset in (1, 2):
            with self.subTest(conflict_day=offset):
                appointment = self.reserve(day=start + timedelta(days=offset))
                with self.assertRaises(ValidationError):
                    add_days_off(self.barber.pk, start, end)
                self.assertEqual(list(DayOff.objects.values_list("pk", flat=True)), [existing.pk])
                cancel_appointment(appointment)

    def test_ongoing_end_appointment_rejects_entire_range(self):
        appointment = self.reserve()
        existing = DayOff.objects.create(barber=self.barber, date=NOW.date() - timedelta(days=3))
        with patch("django.utils.timezone.now", return_value=appointment.starts_at + timedelta(minutes=10)):
            with self.assertRaises(ValidationError):
                add_days_off(self.barber.pk, NOW.date() - timedelta(days=2), NOW.date())
        self.assertEqual(list(DayOff.objects.values_list("pk", flat=True)), [existing.pk])

    def test_cancelled_appointment_does_not_block_range(self):
        appointment = self.reserve(day=NOW.date() + timedelta(days=1))
        cancel_appointment(appointment)
        add_days_off(self.barber.pk, NOW.date(), NOW.date() + timedelta(days=2))
        self.assertEqual(self.days_off(), {NOW.date() + timedelta(days=n) for n in range(3)})

    def test_owner_can_add_for_each_barber_but_barber_only_for_self(self):
        data = {"action": "add_off", "date": NOW.date(), "end_date": NOW.date() + timedelta(days=2)}
        self.client.force_login(self.barber.user)
        self.assertEqual(self.client.post(self.hours_url(self.other), data).status_code, 403)
        self.assertFalse(DayOff.objects.exists())
        self.assertRedirects(self.client.post(self.hours_url(), data), self.hours_url())
        self.client.force_login(self.owner)
        for barber in (self.barber, self.other):
            with self.subTest(barber=barber.pk):
                self.assertRedirects(self.client.post(self.hours_url(barber), data), self.hours_url(barber))
                self.assertEqual(len(self.days_off(barber)), 3)

    def test_range_post_requires_login_and_csrf(self):
        data = {"action": "add_off", "date": NOW.date(), "end_date": NOW.date() + timedelta(days=2)}
        self.assertEqual(self.client.post(self.hours_url(), data).status_code, 302)
        secure_client = Client(enforce_csrf_checks=True)
        secure_client.force_login(self.owner)
        self.assertEqual(secure_client.post(self.hours_url(), data).status_code, 403)
        self.assertFalse(DayOff.objects.exists())
        secure_client.get(self.hours_url())
        data["csrfmiddlewaretoken"] = secure_client.cookies["csrftoken"].value
        self.assertEqual(secure_client.post(self.hours_url(), data).status_code, 302)
        self.assertEqual(len(self.days_off()), 3)

    def test_removing_one_day_preserves_the_rest_of_the_range(self):
        start = NOW.date()
        add_days_off(self.barber.pk, start, start + timedelta(days=2))
        self.client.force_login(self.barber.user)
        response = self.client.post(self.hours_url(), {"action": "remove_off", "date": start + timedelta(days=1)})
        self.assertRedirects(response, self.hours_url())
        self.assertEqual(self.days_off(), {start, start + timedelta(days=2)})

    def test_bilingual_help_and_conflict_retain_both_dates(self):
        self.client.force_login(self.owner)
        start, end = NOW.date(), NOW.date() + timedelta(days=2)
        self.reserve(day=end)
        for language, start_label, end_label, help_text in (
            ("en", "Start date", "End date (optional)", "Leave the end date blank for a single day off."),
            ("bg", "Начална дата", "Крайна дата (незадължително)", "За един почивен ден оставете крайната дата празна."),
        ):
            with self.subTest(language=language):
                url = self.hours_url() + f"?lang={language}"
                response = self.client.get(url)
                for text in (start_label, end_label, help_text, "366"):
                    self.assertContains(response, text)
                response = self.client.post(url, {"action": "add_off", "date": start, "end_date": end})
                self.assertTrue(response.context["off_form"].non_field_errors())
                for day in (start, end):
                    self.assertContains(response, f'value="{day.isoformat()}"')
                self.assertFalse(DayOff.objects.exists())

    def test_schedule_filter_keeps_single_date_form(self):
        self.client.force_login(self.barber.user)
        response = self.client.get(reverse("booking:schedule"), {"date": NOW.date(), "view": "day"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="end_date"')
        self.assertEqual(set(DayOffForm().fields), {"date"})

    def test_public_slots_exclude_every_covered_day_and_leave_neighbours(self):
        start = NOW.date() + timedelta(days=1)
        add_days_off(self.barber.pk, start, start + timedelta(days=2))
        for offset in range(5):
            with self.subTest(day=offset):
                response = self.client.get(reverse("booking:book"), self.selection(date=NOW.date() + timedelta(days=offset)))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(bool(response.context["slots"]), offset in (0, 4))
