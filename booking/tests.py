"""Synthetic, isolated booking regressions; PostgreSQL tests exercise real locks."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal
from io import StringIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import translation

from catalogue.models import Service
from .models import Appointment, Barber, DayOff, ShopManager, WorkingHours
from .rules import SOFIA, available_slots, cancel_appointment, change_day_off, normalize_phone, replace_hours, reserve

NOW = datetime(2030, 1, 7, 9, 0, tzinfo=SOFIA)  # Monday, synthetic future clock.
PASSWORD = "Synthetic#Marble739!"


class BookingFixtures:
    def setUp(self):
        super().setUp()
        cache.clear()
        translation.deactivate_all()
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.addCleanup(translation.deactivate_all)
        self.service = Service.objects.create(name="Synthetic haircut", name_bg="Тестово подстригване", duration_minutes=30, price=Decimal("20.50"))
        self.barber = self.make_barber("barber-one")
        self.other = self.make_barber("barber-two")
        self.owner = get_user_model().objects.create_user("shop-owner", password=PASSWORD)
        ShopManager.objects.create(user=self.owner)

    def make_barber(self, username):
        user = get_user_model().objects.create_user(username, password=PASSWORD)
        barber = Barber.objects.create(user=user, name=username)
        barber.services.add(self.service)
        WorkingHours.objects.bulk_create([WorkingHours(barber=barber, weekday=day, opens_at=time(10), closes_at=time(18)) for day in range(7)])
        return barber

    def reserve(self, **overrides):
        data = dict(barber_id=self.barber.pk, service_id=self.service.pk, day=NOW.date(), clock=time(10), request_id=uuid.uuid4(), customer_name="Synthetic Client", phone="+359881234567", email="synthetic@example.invalid")
        data.update(overrides)
        return reserve(**data)

    def selection(self, **overrides):
        data = dict(service=self.service.pk, barber=self.barber.pk, date=NOW.date().isoformat(), time="10:00")
        data.update(overrides)
        return data

    def booking_payload(self, client=None, **overrides):
        client = client or self.client
        selected = self.selection(**{key: value for key, value in overrides.items() if key in ("service", "barber", "date", "time")})
        response = client.get(reverse("booking:book"), selected)
        self.assertEqual(response.status_code, 200)
        data = dict(selected, request_id=client.session["booking_requests"][-1], customer_name="Synthetic Client", phone="+359881234567", email="synthetic@example.invalid")
        data.update(overrides)
        return data

    def profile_payload(self, **overrides):
        data = dict(username="new-barber", name="New Barber", password=PASSWORD, password_confirm=PASSWORD, services=[self.service.pk], is_active="on", open_0="on", start_0="10:00", end_0="18:00")
        data.update(overrides)
        return data


class AvailabilityTests(BookingFixtures, TestCase):
    def test_phone_requires_bulgarian_prefix_and_nine_ascii_digits(self):
        # The rule specifies digit count, not mobile operator prefixes.
        for valid in ("0888123456", "+359888123456", "0123456789", "+359012345678"):
            with self.subTest(valid=valid):
                self.assertEqual(normalize_phone(valid), valid)
                self.assertEqual(normalize_phone(f" \t{valid}\r\n"), valid)
        for invalid in (
            "", " \t", "088812345", "08881234567", "+35988812345", "+3598881234567",
            "888123456", "359888123456", "+358888123456", "00359888123456",
            "0888 123456", "0888-123456", "0(888)123456", "0888.123456",
            "0888\n123456", "+359 888123456", "０888123456", "0８８８１２３４５６",
            "+359٨٨٨١٢٣٤٥٦", "088812345x", "++359888123456",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                normalize_phone(invalid)

    def test_direct_reservation_rejects_invalid_phone_without_consuming_token(self):
        token = uuid.uuid4()
        for invalid in ("", "088812345", "+3598881234567", "0888 123456", "+358888123456"):
            with self.subTest(phone=invalid), self.assertRaises(ValidationError):
                self.reserve(phone=invalid, request_id=token)
            self.assertFalse(Appointment.objects.exists())
        appointment = self.reserve(phone=" 0888123456 ", request_id=token)
        self.assertEqual(appointment.phone, "0888123456")
        self.assertEqual(appointment.request_id, token)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_horizon_inclusive_and_sofia_local_day(self):
        for offset in (0, 28):
            self.assertTrue(available_slots(self.barber, self.service, NOW.date() + timedelta(days=offset)))
        for offset in (-1, 29):
            self.assertEqual(available_slots(self.barber, self.service, NOW.date() + timedelta(days=offset)), [])
        near_midnight = datetime(2030, 1, 7, 22, 30, tzinfo=datetime_timezone.utc)
        self.assertTrue(available_slots(self.barber, self.service, NOW.date() + timedelta(days=29), now=near_midnight))

    def test_quarter_hour_starts_strict_future_and_exact_duration(self):
        self.service.duration_minutes = 35
        self.service.save()
        WorkingHours.objects.filter(barber=self.barber, weekday=0).update(opens_at=time(10, 1), closes_at=time(11))
        slots = available_slots(self.barber, self.service, NOW.date())
        self.assertEqual([slot.time() for slot in slots], [time(10, 15)])
        self.assertEqual(available_slots(self.barber, self.service, NOW.date(), now=slots[0]), [])
        appointment = self.reserve(clock=time(10, 15))
        self.assertEqual(appointment.ends_at - appointment.starts_at, timedelta(minutes=35))

    def test_inactive_service_barber_login_and_unassigned_service_not_bookable(self):
        for target, field in ((self.service, "is_active"), (self.barber, "is_active"), (self.barber.user, "is_active")):
            with self.subTest(target=type(target).__name__):
                setattr(target, field, False)
                target.save()
                self.assertEqual(available_slots(self.barber, self.service, NOW.date()), [])
                with self.assertRaises(ValidationError):
                    self.reserve()
                setattr(target, field, True)
                target.save()
        self.barber.services.clear()
        with self.assertRaises(ValidationError):
            self.reserve()

    def test_days_off_and_no_shift_block_booking(self):
        DayOff.objects.create(barber=self.barber, date=NOW.date())
        self.assertEqual(available_slots(self.barber, self.service, NOW.date()), [])
        DayOff.objects.all().delete()
        self.barber.working_hours.all().delete()
        with self.assertRaises(ValidationError):
            self.reserve()

    def test_overlap_rejected_adjacency_and_other_barber_allowed(self):
        self.reserve()
        with self.assertRaises(ValidationError):
            self.reserve(clock=time(10, 15))
        self.reserve(clock=time(10, 30))
        self.reserve(barber_id=self.other.pk)
        self.assertEqual(Appointment.objects.count(), 3)

    def test_snapshot_preserved_when_service_changes(self):
        appointment = self.reserve()
        self.service.name = "Changed"
        self.service.duration_minutes = 60
        self.service.price = Decimal("99")
        self.service.save()
        appointment.refresh_from_db()
        self.assertEqual((appointment.service_name, appointment.duration_minutes, appointment.price), ("Synthetic haircut", 30, Decimal("20.50")))

    def test_repeat_request_returns_same_appointment(self):
        token = uuid.uuid4()
        first = self.reserve(request_id=token)
        second = self.reserve(request_id=token)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_cancellation_retains_record_releases_slot_and_is_idempotent(self):
        appointment = self.reserve()
        cancel_appointment(appointment, future_only=True)
        cancelled = appointment.cancelled_at
        cancel_appointment(appointment, future_only=True)
        appointment.refresh_from_db()
        self.assertEqual(appointment.cancelled_at, cancelled)
        self.reserve()
        self.assertEqual(Appointment.objects.count(), 2)

    def test_customer_cancellation_at_start_is_rejected(self):
        appointment = self.reserve()
        with patch("django.utils.timezone.now", return_value=appointment.starts_at):
            with self.assertRaises(ValidationError):
                cancel_appointment(appointment, future_only=True)
        appointment.refresh_from_db()
        self.assertIsNone(appointment.cancelled_at)

    def test_conflicting_hours_rejected_atomically_including_ongoing_appointment(self):
        appointment = self.reserve()
        original = list(self.barber.working_hours.values_list("weekday", "opens_at", "closes_at"))
        for now in (NOW, appointment.starts_at + timedelta(minutes=5)):
            with patch("django.utils.timezone.now", return_value=now), self.assertRaises(ValidationError):
                replace_hours(self.barber.pk, {0: (time(11), time(17))})
            self.assertEqual(list(self.barber.working_hours.values_list("weekday", "opens_at", "closes_at")), original)

    def test_conflicting_day_off_rejected_then_accepted_after_cancel(self):
        appointment = self.reserve()
        with self.assertRaises(ValidationError):
            change_day_off(self.barber.pk, NOW.date())
        self.assertFalse(DayOff.objects.exists())
        cancel_appointment(appointment)
        change_day_off(self.barber.pk, NOW.date())
        self.assertTrue(DayOff.objects.exists())
        change_day_off(self.barber.pk, NOW.date(), remove=True)
        self.assertFalse(DayOff.objects.exists())

    def test_elapsed_bookings_do_not_block_schedule_change(self):
        appointment = self.reserve()
        with patch("django.utils.timezone.now", return_value=appointment.ends_at):
            replace_hours(self.barber.pk, {})
        self.assertFalse(self.barber.working_hours.exists())


class PublicBookingTests(BookingFixtures, TestCase):
    def test_bilingual_selection_details_errors_and_confirmation(self):
        for language, label, help_text, valid_phone in (
            ("bg", "Телефон", "Примери: 0888123456 / +359888123456.", "0888123456"),
            ("en", "Phone", "Examples: 0888123456 / +359888123456.", "+359888123456"),
        ):
            with self.subTest(language=language):
                client = Client()
                selected = self.selection(lang=language, time="11:00" if language == "en" else "10:00")
                response = client.get(reverse("booking:book"), selected)
                self.assertContains(response, f'<html lang="{language}">')
                self.assertContains(response, label)
                self.assertContains(response, 'name="phone"')
                self.assertContains(response, 'type="tel"')
                self.assertContains(response, f'time={selected["time"]}#details"')
                self.assertContains(response, 'id="details"')
                self.assertContains(response, help_text)
                self.assertTrue(response.context["form"].fields["phone"].required)
                payload = self.booking_payload(client=client, time=selected["time"], phone=f" {valid_phone} ")
                original_count = Appointment.objects.count()
                for invalid_phone in (
                    "bad", "", "088812345", "08881234567", "+35988812345",
                    "+3598881234567", "0888 123456", "0" * 81, "0888123456\x00",
                ):
                    with self.subTest(phone=invalid_phone):
                        invalid = client.post(reverse("booking:book"), dict(payload, phone=invalid_phone))
                        self.assertEqual(invalid.status_code, 200)
                        form = invalid.context["form"]
                        self.assertEqual(set(form.errors), {"phone"})
                        self.assertContains(invalid, "Enter 0 or +359 followed by exactly 9 digits")
                        self.assertContains(invalid, "Въведете 0 или +359, следвани от точно 9 цифри")
                        self.assertContains(invalid, "e.g. 0888123456 or +359888123456.")
                        self.assertContains(invalid, help_text)
                        self.assertEqual(form["phone"].value(), invalid_phone)
                        for field in ("service", "barber", "date", "time", "request_id", "customer_name", "email"):
                            self.assertEqual(str(form[field].value()), str(payload[field]))
                            self.assertContains(invalid, str(form[field]), html=True)
                        self.assertContains(invalid, str(form["phone"]), html=True)
                        self.assertEqual(Appointment.objects.count(), original_count)
                response = client.post(reverse("booking:book"), payload, follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.redirect_chain), 1)
                self.assertContains(response, "Synthetic Client")
                self.assertContains(response, valid_phone)
                self.assertEqual(Appointment.objects.count(), original_count + 1)
                self.assertEqual(Appointment.objects.get(request_id=payload["request_id"]).phone, valid_phone)

    def test_booking_session_nonce_required_and_recent_tokens_bounded(self):
        forged = dict(self.selection(), request_id=str(uuid.uuid4()), customer_name="Synthetic Client", phone="0888123456")
        self.assertEqual(self.client.post(reverse("booking:book"), forged).status_code, 403)
        first = self.booking_payload()
        for _ in range(30):
            self.client.get(reverse("booking:book"), self.selection())
        self.assertEqual(len(self.client.session["booking_requests"]), 30)
        self.assertEqual(self.client.post(reverse("booking:book"), first).status_code, 403)
        self.assertFalse(Appointment.objects.exists())

    def test_public_retry_same_confirmation_and_session_private(self):
        payload = self.booking_payload()
        first = self.client.post(reverse("booking:book"), payload)
        second = self.client.post(reverse("booking:book"), payload)
        self.assertEqual(first.url, second.url)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(Client().get(first.url).status_code, 404)
        appointment = Appointment.objects.get()
        cancel_url = reverse("booking:customer_cancel", args=[appointment.reference])
        self.assertEqual(Client().post(cancel_url).status_code, 404)
        self.assertEqual(self.client.get(cancel_url).status_code, 405)
        self.assertEqual(self.client.post(cancel_url).status_code, 302)
        appointment.refresh_from_db()
        self.assertIsNotNone(appointment.cancelled_at)

    def test_retry_after_catalogue_deactivation_returns_original_snapshot(self):
        payload = self.booking_payload()
        first = self.client.post(reverse("booking:book"), payload)
        self.service.is_active = False
        self.service.save()
        self.barber.is_active = False
        self.barber.save()
        second = self.client.post(reverse("booking:book"), dict(payload, phone="changed invalid data"))
        self.assertEqual(first.url, second.url)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(Appointment.objects.get().phone, "+359881234567")

    def test_customer_cancel_endpoint_rejects_started_appointment(self):
        self.client.post(reverse("booking:book"), self.booking_payload())
        appointment = Appointment.objects.get()
        with patch("django.utils.timezone.now", return_value=appointment.starts_at):
            response = self.client.post(reverse("booking:customer_cancel", args=[appointment.reference]), follow=True)
        self.assertContains(response, "Only future appointments")
        appointment.refresh_from_db()
        self.assertIsNone(appointment.cancelled_at)

    def test_booking_limit_blocks_new_requests_but_allows_retry(self):
        payload = self.booking_payload()
        first = self.client.post(reverse("booking:book"), payload)
        stale_payload = self.booking_payload(time="11:00")
        # A valid issued request for a subsequently occupied slot still counts.
        self.reserve(clock=time(11))
        for _ in range(29):
            self.assertEqual(self.client.post(reverse("booking:book"), stale_payload).status_code, 200)
        self.assertEqual(self.client.post(reverse("booking:book"), stale_payload).status_code, 429)
        self.assertEqual(self.client.post(reverse("booking:book"), payload).url, first.url)

    def test_missing_name_phone_and_bad_optional_email_rejected(self):
        payload = self.booking_payload()
        for field, value in (("phone", ""), ("customer_name", " "), ("email", "not-an-email"), ("time", "10:07")):
            with self.subTest(field=field):
                response = self.client.post(reverse("booking:book"), dict(payload, **{field: value}))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertFalse(Appointment.objects.exists())
        response = self.client.post(reverse("booking:book"), dict(payload, email=""))
        self.assertEqual(response.status_code, 302)

    def test_tampered_barber_service_and_outside_dates_rejected(self):
        payload = self.booking_payload()
        self.other.services.clear()
        for override in ({"barber": self.other.pk}, {"service": 999999}, {"date": "2030-01-06"}, {"date": "2030-02-05"}):
            response = self.client.post(reverse("booking:book"), dict(payload, **override))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.assertFalse(Appointment.objects.exists())

    def test_csrf_required_for_booking_login_and_cancellation(self):
        client = Client(enforce_csrf_checks=True)
        payload = self.booking_payload(client=client)
        self.assertEqual(client.post(reverse("booking:book"), payload).status_code, 403)
        self.assertEqual(client.post(reverse("booking:login"), {"username": self.owner.username, "password": PASSWORD}).status_code, 403)
        response = client.post(reverse("booking:book"), dict(payload, csrfmiddlewaretoken=client.cookies["csrftoken"].value))
        self.assertEqual(response.status_code, 302)
        appointment = Appointment.objects.get()
        self.assertEqual(client.post(reverse("booking:customer_cancel", args=[appointment.reference])).status_code, 403)


class StaffTests(BookingFixtures, TestCase):
    def test_owner_and_superuser_have_branded_dashboard_without_staff_flag(self):
        superuser = get_user_model().objects.create_superuser("super-owner", password=PASSWORD)
        for user in (self.owner, superuser):
            self.client.force_login(user)
            for language, heading in (("en", "Alan Barberhouse"), ("bg", "Alan Barberhouse")):
                response = self.client.get(reverse("booking:dashboard"), {"lang": language})
                self.assertContains(response, heading)
                self.assertContains(response, reverse("booking:barber_create"))
                self.assertNotContains(response, "Django administration")
        self.assertFalse(self.owner.is_staff)

    def test_login_fixed_destination_logout_post_only_and_no_access_accounts(self):
        response = self.client.post(reverse("booking:login") + "?next=https://example.invalid/", {"username": self.owner.username, "password": PASSWORD})
        self.assertRedirects(response, reverse("booking:dashboard"))
        self.assertEqual(self.client.get(reverse("booking:logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("booking:logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        unassigned = get_user_model().objects.create_user("unassigned", password=PASSWORD, is_staff=True)
        for user in (unassigned, self.barber.user):
            if user == self.barber.user:
                self.barber.is_active = False
                self.barber.save()
            response = self.client.post(reverse("booking:login"), {"username": user.username, "password": PASSWORD})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_anonymous_unassigned_and_inactive_accounts_cannot_access_staff(self):
        self.assertEqual(self.client.get(reverse("booking:dashboard")).status_code, 302)
        unassigned = get_user_model().objects.create_user("unassigned")
        self.client.force_login(unassigned)
        self.assertEqual(self.client.get(reverse("booking:dashboard")).status_code, 403)
        self.client.force_login(self.barber.user)
        self.barber.is_active = False
        self.barber.save()
        self.assertEqual(self.client.get(reverse("booking:dashboard")).status_code, 403)
        self.owner.is_active = False
        self.owner.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("booking:dashboard")).status_code, 302)

    def test_owner_create_barber_password_hashed_services_and_initial_hours(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("booking:barber_create"), self.profile_payload())
        self.assertEqual(response.status_code, 302)
        barber = Barber.objects.get(user__username="new-barber")
        self.assertTrue(barber.user.check_password(PASSWORD))
        self.assertNotEqual(barber.user.password, PASSWORD)
        self.assertFalse(barber.user.is_staff or barber.user.is_superuser)
        self.assertEqual(list(barber.services.all()), [self.service])
        self.assertEqual(list(barber.working_hours.values_list("weekday", "opens_at", "closes_at")), [(0, time(10), time(18))])

    def test_invalid_password_confirmation_username_and_hours_create_nothing(self):
        self.client.force_login(self.owner)
        for override in ({"password_confirm": "mismatch"}, {"password_confirm": ""}, {"password": "123", "password_confirm": "123"}, {"username": "bad name"}, {"username": self.barber.user.username}, {"start_0": "18:00", "end_0": "10:00"}):
            with self.subTest(override=override):
                response = self.client.post(reverse("booking:barber_create"), self.profile_payload(**override))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(Barber.objects.count(), 2)

    def test_edit_keep_reset_password_and_deactivate_retains_appointments(self):
        appointment = self.reserve()
        self.client.force_login(self.owner)
        url = reverse("booking:barber_edit", args=[self.barber.pk])
        payload = self.profile_payload(username=self.barber.user.username, password="", password_confirm="", name="Edited Barber")
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.barber.user.refresh_from_db()
        self.assertTrue(self.barber.user.check_password(PASSWORD))
        reset = "Changed#Quartz824!"
        self.assertEqual(self.client.post(url, dict(payload, password=reset, password_confirm=reset)).status_code, 302)
        self.barber.user.refresh_from_db()
        self.assertTrue(self.barber.user.check_password(reset))
        payload.pop("is_active")
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.barber.refresh_from_db()
        self.barber.user.refresh_from_db()
        self.assertFalse(self.barber.is_active or self.barber.user.is_active)
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk, cancelled_at__isnull=True).exists())

    def test_barber_cannot_manage_accounts_services_or_colleague_schedule(self):
        self.client.force_login(self.barber.user)
        for url in (reverse("booking:barber_create"), reverse("booking:barber_edit", args=[self.barber.pk]), reverse("booking:services"), reverse("booking:service_create"), reverse("booking:service_edit", args=[self.service.pk]), reverse("booking:hours", args=[self.other.pk])):
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    self.assertEqual(method(url).status_code, 403)

    def test_colleague_schedule_only_contains_anonymous_blocks(self):
        appointment = self.reserve(barber_id=self.other.pk)
        self.client.force_login(self.barber.user)
        response = self.client.get(reverse("booking:schedule"), {"date": NOW.date(), "barber": self.other.pk, "view": "day", "lang": "en"})
        self.assertContains(response, "Booked")
        self.assertContains(response, "10:00")
        for private in (appointment.customer_name, appointment.phone, appointment.email, str(appointment.reference), reverse("booking:staff_cancel", args=[appointment.pk]), reverse("booking:hours", args=[self.other.pk])):
            self.assertNotContains(response, private)
        row = response.context["columns"][0]["days"][0]["appointments"][0]
        self.assertEqual(set(row), {"starts_at", "ends_at"})
        self.assertEqual(self.client.post(reverse("booking:staff_cancel", args=[appointment.pk])).status_code, 403)

    def test_own_and_owner_appointments_details_cancel_permissions(self):
        for user, barber in ((self.barber.user, self.barber), (self.owner, self.other)):
            appointment = self.reserve(barber_id=barber.pk)
            self.client.force_login(user)
            response = self.client.get(reverse("booking:schedule"), {"date": NOW.date(), "barber": barber.pk})
            self.assertContains(response, appointment.customer_name)
            self.assertContains(response, appointment.phone)
            self.assertContains(response, appointment.email)
            url = reverse("booking:staff_cancel", args=[appointment.pk])
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(self.client.post(url).status_code, 302)
            appointment.refresh_from_db()
            self.assertIsNotNone(appointment.cancelled_at)

    def test_cancel_redirect_drops_the_displayed_schedule_filters(self):
        # Reproduces a known UX finding (docs/ui-audit.md #5): cancelling from a
        # filtered day/barber view returns to the default schedule instead of
        # the filters the user was reviewing. This pins the current behavior so
        # a future template/view change is a deliberate, reviewed decision.
        appointment = self.reserve(barber_id=self.barber.pk)
        self.client.force_login(self.barber.user)
        filtered_schedule = reverse("booking:schedule") + f"?date={NOW.date()}&view=day&barber={self.barber.pk}"
        response = self.client.post(
            reverse("booking:staff_cancel", args=[appointment.pk]),
            HTTP_REFERER=f"http://testserver{filtered_schedule}",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("booking:schedule"))
        self.assertNotIn("date=", response.url)
        self.assertNotIn("barber=", response.url)

    def test_own_hours_and_days_off_edits_conflict_feedback(self):
        self.client.force_login(self.barber.user)
        url = reverse("booking:hours", args=[self.barber.pk])
        self.assertEqual(self.client.post(url, {"action": "hours", "open_0": "on", "start_0": "10:00", "end_0": "18:00"}).status_code, 302)
        self.reserve()
        response = self.client.post(url, {"action": "hours"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["hours"].non_field_errors())
        response = self.client.post(url, {"action": "add_off", "date": NOW.date()})
        self.assertTrue(response.context["off_form"].non_field_errors())
        tomorrow = NOW.date() + timedelta(days=1)
        self.assertEqual(self.client.post(url, {"action": "add_off", "date": tomorrow}).status_code, 302)
        self.assertTrue(DayOff.objects.filter(barber=self.barber, date=tomorrow).exists())
        self.assertEqual(self.client.post(url, {"action": "remove_off", "date": tomorrow}).status_code, 302)

    def test_owner_service_management_validates_and_preserves_snapshot(self):
        appointment = self.reserve()
        self.client.force_login(self.owner)
        data = dict(name="Changed service", name_bg="Променена услуга", description="", description_bg="", price="31.25", duration_minutes=45, display_order=0, is_active="on")
        url = reverse("booking:service_edit", args=[self.service.pk])
        self.assertEqual(self.client.post(url, dict(data, duration_minutes=0)).status_code, 200)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.service.refresh_from_db()
        self.assertEqual(self.service.price, Decimal("31.25"))
        appointment.refresh_from_db()
        self.assertEqual(appointment.price, Decimal("20.50"))
        self.assertEqual(self.client.post(reverse("booking:service_create"), dict(data, name="New service")).status_code, 302)
        self.assertEqual(Service.objects.count(), 2)

    def test_staff_csrf_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url, data in ((reverse("booking:barber_create"), self.profile_payload()), (reverse("booking:hours", args=[self.barber.pk]), {"action": "hours"}), (reverse("booking:logout"), {})):
            self.assertEqual(client.post(url, data).status_code, 403)

    def test_bilingual_owner_forms_have_translated_labels_and_validation(self):
        self.client.force_login(self.owner)
        for language, label, required in (("en", "Username", "This field is required."), ("bg", "Потребителско име", "Това поле е задължително.")):
            url = reverse("booking:barber_create") + f"?lang={language}"
            response = self.client.get(url)
            self.assertContains(response, label)
            response = self.client.post(url, self.profile_payload(username=""))
            self.assertContains(response, required)
            self.assertContains(response, 'aria-invalid="true"')

    def test_login_throttle_ignores_forwarded_header(self):
        for attempt in range(20):
            response = self.client.post(reverse("booking:login"), {"username": "missing", "password": "wrong"}, HTTP_X_FORWARDED_FOR=f"192.0.2.{attempt}")
            self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("booking:login"), {"username": "missing", "password": "wrong"}, HTTP_X_FORWARDED_FOR="192.0.2.99")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "900")


class OwnerBootstrapTests(TestCase):
    def create_owner(self, username="bootstrap-owner", passwords=None):
        output = StringIO()
        with patch("builtins.input", return_value=username), patch("booking.management.commands.create_shop_owner.getpass", side_effect=passwords or [PASSWORD, PASSWORD]):
            call_command("create_shop_owner", stdout=output)
        return output.getvalue()

    def test_interactive_owner_has_hashed_password_role_and_no_admin_flags(self):
        output = self.create_owner()
        user = get_user_model().objects.get(username="bootstrap-owner")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(ShopManager.objects.filter(user=user).exists())
        self.assertNotIn(PASSWORD, output)
        self.assertIn("/staff/login/", output)

    def test_invalid_credentials_mismatch_duplicate_and_cancel_leave_no_extra_accounts(self):
        for username, passwords in (("invalid name", [PASSWORD, PASSWORD]), ("", [PASSWORD, PASSWORD]), ("weak", ["123", "123"]), ("missing-password", ["", ""]), ("mismatch", [PASSWORD, "other"])):
            with self.subTest(username=username), self.assertRaises(CommandError):
                self.create_owner(username, passwords)
        self.assertFalse(get_user_model().objects.exists())
        self.create_owner()
        with self.assertRaises(CommandError):
            self.create_owner()
        with patch("builtins.input", side_effect=EOFError), self.assertRaises(CommandError):
            call_command("create_shop_owner", stdout=StringIO())
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(ShopManager.objects.count(), 1)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL exclusion constraint and row locks require PostgreSQL")
class PostgreSQLBookingTests(BookingFixtures, TransactionTestCase):
    def direct_appointment(self, **overrides):
        start = NOW.replace(hour=10)
        data = dict(barber=self.barber, service=self.service, request_id=uuid.uuid4(), service_name=self.service.name, duration_minutes=30, price=self.service.price, starts_at=start, ends_at=start + timedelta(minutes=30), customer_name="Synthetic Client", phone="0888123456")
        data.update(overrides)
        return Appointment.objects.create(**data)

    def test_database_overlap_exclusion_and_cancelled_adjacent_other_barber_cases(self):
        first = self.direct_appointment()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.direct_appointment(starts_at=first.starts_at + timedelta(minutes=15))
        self.direct_appointment(starts_at=first.ends_at, ends_at=first.ends_at + timedelta(minutes=30))
        self.direct_appointment(barber=self.other)
        self.direct_appointment(cancelled_at=NOW)
        first.cancelled_at = NOW
        first.save(update_fields=["cancelled_at"])
        self.direct_appointment()
        self.assertEqual(Appointment.objects.count(), 5)

    def test_simultaneous_same_slot_only_one_reservation_succeeds(self):
        barrier = Barrier(2)

        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                try:
                    return ("created", self.reserve().pk)
                except ValidationError:
                    return ("conflict", None)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertCountEqual([result[0] for result in results], ["created", "conflict"])
        self.assertEqual(Appointment.objects.count(), 1)

    def test_simultaneous_booking_and_day_off_never_create_invalid_schedule(self):
        barrier = Barrier(2)

        def attempt(kind):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                try:
                    self.reserve() if kind == "book" else change_day_off(self.barber.pk, NOW.date())
                    return "success"
                except ValidationError:
                    return "conflict"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ["book", "off"]))
        self.assertCountEqual(results, ["success", "conflict"])
        self.assertFalse(Appointment.objects.exists() and DayOff.objects.exists())

    def test_simultaneous_identical_request_is_idempotent(self):
        barrier = Barrier(2)
        token = uuid.uuid4()

        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                return self.reserve(request_id=token).pk
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(Appointment.objects.count(), 1)

    def test_simultaneous_booking_and_hours_change_never_create_invalid_schedule(self):
        barrier = Barrier(2)

        def attempt(kind):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                try:
                    self.reserve() if kind == "book" else replace_hours(self.barber.pk, {})
                    return "success"
                except ValidationError:
                    return "conflict"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ["book", "hours"]))
        self.assertCountEqual(results, ["success", "conflict"])
        self.assertFalse(Appointment.objects.exists() and not self.barber.working_hours.exists())
