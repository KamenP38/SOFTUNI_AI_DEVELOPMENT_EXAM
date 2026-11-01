"""Self-service assignment regressions using synthetic test-database data."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from catalogue.models import Service
from .forms import MyServicesForm
from .models import Appointment, Barber
from .rules import AvailabilitySnapshot
from .tests import BookingFixtures, NOW


class MyServicesTests(BookingFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("booking:my_services")
        self.additional = Service.objects.create(
            name="Synthetic beard", name_bg="Тестова брада", duration_minutes=15,
            price=Decimal("12.00"),
        )
        self.inactive = Service.objects.create(
            name="Synthetic retired service", name_bg="Тестова неактивна услуга",
            duration_minutes=45, price=Decimal("30.00"), is_active=False,
        )
        self.client.force_login(self.barber.user)

    def assigned(self, barber=None):
        return set((barber or self.barber).services.values_list("pk", flat=True))

    def test_only_authenticated_active_barbers_can_read_or_submit(self):
        unassigned = get_user_model().objects.create_user("synthetic-unassigned", is_staff=True)
        for user, expected in ((None, 302), (unassigned, 403), (self.owner, 403)):
            client = Client()
            if user:
                client.force_login(user)
            for method in (client.get, client.post):
                with self.subTest(user=user, method=method.__name__):
                    self.assertEqual(method(self.url).status_code, expected)
        self.barber.is_active = False
        self.barber.save(update_fields=["is_active"])
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(self.url).status_code, 403)
        self.barber.is_active = True
        self.barber.save(update_fields=["is_active"])
        self.barber.user.is_active = False
        self.barber.user.save(update_fields=["is_active"])
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(self.url).status_code, 302)
        self.assertEqual(self.assigned(), {self.service.pk})

    def test_tampered_target_and_profile_fields_change_only_own_assignments(self):
        users_before = list(get_user_model().objects.order_by("pk").values())
        barbers_before = list(Barber.objects.order_by("pk").values())
        catalogue_before = list(Service.objects.order_by("pk").values())
        response = self.client.post(self.url, {
            "services": [self.additional.pk], "barber": self.other.pk,
            "barber_id": self.other.pk, "pk": self.other.pk, "user": self.other.user_id,
            "username": "intruder", "password": "Changed#Pass123!", "name": "Changed",
            "is_active": "", "is_staff": "on", "is_superuser": "on",
            "price": "0.01", "duration_minutes": "1", "name_bg": "Changed",
        })
        self.assertRedirects(response, self.url)
        self.assertEqual(self.assigned(), {self.additional.pk})
        self.assertEqual(self.assigned(self.other), {self.service.pk})
        self.assertEqual(list(get_user_model().objects.order_by("pk").values()), users_before)
        self.assertEqual(list(Barber.objects.order_by("pk").values()), barbers_before)
        self.assertEqual(list(Service.objects.order_by("pk").values()), catalogue_before)
        self.assertEqual(self.client.post(f"{self.url}{self.other.pk}/", {}).status_code, 404)

    def test_get_does_not_mutate_and_other_methods_are_rejected(self):
        response = self.client.get(self.url, {"services": self.additional.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        for method in ("put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(self.url).status_code, 405)
        self.assertEqual(self.assigned(), {self.service.pk})
        response = self.client.post(self.url, {"services": [self.additional.pk]})
        self.assertIn("no-store", response["Cache-Control"])

    def test_csrf_is_required_and_valid_token_allows_save(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.barber.user)
        self.assertEqual(client.post(self.url, {}).status_code, 403)
        self.assertEqual(self.assigned(), {self.service.pk})
        response = client.get(self.url)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        response = client.post(self.url, {
            "services": [self.additional.pk],
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.assigned(), {self.additional.pk})

    def test_inactive_assignment_can_be_kept_removed_but_not_readded(self):
        self.barber.services.add(self.inactive)
        response = self.client.get(self.url, {"lang": "en"})
        self.assertContains(response, "Synthetic retired service (inactive)")
        self.assertEqual(set(response.context["form"].initial["services"]), {self.service, self.inactive})
        self.assertEqual(self.client.post(self.url, {"services": [self.inactive.pk, self.additional.pk]}).status_code, 302)
        self.assertEqual(self.assigned(), {self.inactive.pk, self.additional.pk})
        self.assertEqual(self.client.post(self.url, {"services": [self.additional.pk]}).status_code, 302)
        response = self.client.post(self.url, {"services": [self.inactive.pk, self.service.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("services", response.context["form"].errors)
        self.assertEqual(self.assigned(), {self.additional.pk})

    def test_invalid_selections_never_partially_write(self):
        for invalid in (self.inactive.pk, 999999, "not-an-id"):
            with self.subTest(invalid=invalid):
                response = self.client.post(self.url, {"services": [self.additional.pk, invalid]})
                self.assertEqual(response.status_code, 200)
                self.assertIn("services", response.context["form"].errors)
                self.assertEqual(self.assigned(), {self.service.pk})

    def test_empty_submission_disables_new_bookings_and_active_service_can_be_readded(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 302)
        self.assertEqual(self.assigned(), set())
        self.assertFalse(any(key[1] == str(self.barber.pk) for key in AvailabilitySnapshot().slots))
        response = self.client.get(reverse("booking:dashboard"), {"lang": "en"})
        self.assertContains(response, "Setup needed · assign an active service")
        self.assertEqual(self.client.post(self.url, {"services": [self.additional.pk]}).status_code, 302)
        key = (str(self.additional.pk), str(self.barber.pk), NOW.date().isoformat())
        self.assertIn(key, AvailabilitySnapshot().slots)

    def test_saved_assignments_immediately_change_public_booking_and_keep_original_retry(self):
        public = Client()
        payload = self.booking_payload(client=public)
        confirmation = public.post(reverse("booking:book"), payload)
        self.assertEqual(confirmation.status_code, 302)
        original = Appointment.objects.values().get()
        stale_payload = self.booking_payload(client=public, time="11:00")
        self.client.post(self.url, {"services": [self.additional.pk]})
        snapshot = AvailabilitySnapshot()
        day = NOW.date().isoformat()
        self.assertNotIn((str(self.service.pk), str(self.barber.pk), day), snapshot.slots)
        self.assertIn((str(self.additional.pk), str(self.barber.pk), day), snapshot.slots)
        self.assertIn((str(self.service.pk), str(self.other.pk), day), snapshot.slots)
        stale = public.post(reverse("booking:book"), stale_payload)
        self.assertEqual(stale.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 1)
        retry = public.post(reverse("booking:book"), payload)
        self.assertEqual(retry.status_code, 302)
        self.assertEqual(retry.url, confirmation.url)
        self.assertEqual(Appointment.objects.values().get(), original)
        new_payload = self.booking_payload(client=public, service=self.additional.pk, time="11:00")
        self.assertEqual(public.post(reverse("booking:book"), new_payload).status_code, 302)
        self.assertEqual(Appointment.objects.count(), 2)

    def test_form_rechecks_service_eligibility_after_validation(self):
        form = MyServicesForm({"services": [self.additional.pk]}, barber=self.barber)
        self.assertTrue(form.is_valid())
        Service.objects.filter(pk=self.additional.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            form.save()
        self.assertEqual(self.assigned(), {self.service.pk})

    def test_form_cannot_restore_inactive_assignment_removed_since_validation(self):
        self.barber.services.add(self.inactive)
        form = MyServicesForm({"services": [self.inactive.pk]}, barber=self.barber)
        self.assertTrue(form.is_valid())
        self.barber.services.remove(self.inactive)
        with self.assertRaises(ValidationError):
            form.save()
        self.assertEqual(self.assigned(), {self.service.pk})

    def test_form_rechecks_both_barber_and_user_activity_after_validation(self):
        for target in (self.barber, self.barber.user):
            with self.subTest(target=type(target).__name__):
                form = MyServicesForm({"services": [self.additional.pk]}, barber=self.barber)
                self.assertTrue(form.is_valid())
                type(target).objects.filter(pk=target.pk).update(is_active=False)
                with self.assertRaises(PermissionDenied):
                    form.save()
                self.assertEqual(self.assigned(), {self.service.pk})
                type(target).objects.filter(pk=target.pk).update(is_active=True)

    def test_bilingual_rendered_form_dashboard_success_warning_and_errors(self):
        self.barber.services.add(self.inactive)
        for language, heading, label, success, warning, inactive, error in (
            ("en", "My services", "Services I offer", "Services saved.",
             "Without an active service selected", "(inactive)", "Select a valid choice."),
            ("bg", "Моите услуги", "Услуги, които предлагам", "Услугите са запазени.",
             "Без избрана активна услуга", "(неактивна)", "Направете валиден избор."),
        ):
            with self.subTest(language=language):
                url = f"{self.url}?lang={language}"
                response = self.client.get(url)
                for text in (heading, label, warning, inactive):
                    self.assertContains(response, text)
                self.assertContains(response, '<input type="checkbox"')
                self.assertContains(response, '<legend>')
                self.assertNotContains(response, 'name="username"')
                dashboard = self.client.get(reverse("booking:dashboard"))
                self.assertContains(dashboard, f'href="{self.url}"')
                self.assertContains(dashboard, heading)
                response = self.client.post(url, {"services": ["999999"]})
                self.assertContains(response, error)
                response = self.client.post(url, {"services": [self.service.pk, self.inactive.pk]}, follow=True)
                self.assertContains(response, success)

    def test_empty_catalogue_explained_in_both_languages(self):
        self.barber.services.clear()
        Service.objects.update(is_active=False)
        for language, message in (
            ("en", "No services are available to select."),
            ("bg", "Няма услуги за избор."),
        ):
            response = self.client.get(self.url, {"lang": language})
            self.assertContains(response, message)
            self.assertNotContains(response, '<input type="checkbox"')
            self.assertEqual(self.client.post(self.url, {}).status_code, 302)

    def test_owner_retains_assignment_controls_and_barber_cannot_use_owner_endpoints(self):
        for name, args in (("barber_edit", [self.barber.pk]), ("barber_edit", [self.other.pk]),
                           ("barber_create", []), ("services", []), ("service_create", []),
                           ("service_edit", [self.service.pk])):
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(reverse(f"booking:{name}", args=args)).status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("booking:dashboard"))
        self.assertNotContains(response, f'href="{self.url}"')
        for barber in (self.barber, self.other):
            payload = self.profile_payload(username=barber.user.username, name=barber.name,
                                           password="", password_confirm="", services=[self.additional.pk])
            self.assertEqual(self.client.post(reverse("booking:barber_edit", args=[barber.pk]), payload).status_code, 302)
            self.assertEqual(self.assigned(barber), {self.additional.pk})
