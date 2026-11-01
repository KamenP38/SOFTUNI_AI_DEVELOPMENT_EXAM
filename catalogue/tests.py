from decimal import Decimal
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from urllib.request import url2pathname

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from .models import Service


def create_service(**overrides):
    fields = {
        "name": "Test haircut",
        "description": "A synthetic service description.",
        "duration_minutes": 35,
        "price": Decimal("23.50"),
    }
    fields.update(overrides)
    return Service.objects.create(**fields)


class ServiceModelTests(TestCase):
    def test_minimum_duration_and_zero_price_are_valid(self):
        service = create_service(duration_minutes=1, price=Decimal("0.00"))
        service.full_clean()
        service.refresh_from_db()
        self.assertEqual(service.duration_minutes, 1)
        self.assertEqual(service.price, Decimal("0.00"))

    def test_money_round_trips_as_decimal(self):
        service = create_service(price=Decimal("12.34"))
        service.refresh_from_db()
        self.assertIsInstance(service.price, Decimal)
        self.assertEqual(service.price, Decimal("12.34"))

    def test_invalid_duration_and_price_fail_model_validation(self):
        for field, value in (
            ("duration_minutes", 0),
            ("duration_minutes", -1),
            ("price", Decimal("-0.01")),
            ("price", Decimal("1.001")),
        ):
            with self.subTest(field=field, value=value):
                service = Service(name="Invalid", duration_minutes=30, price=Decimal("10"))
                setattr(service, field, value)
                with self.assertRaises(ValidationError) as error:
                    service.full_clean()
                self.assertIn(field, error.exception.message_dict)

    def test_database_rejects_nonpositive_durations_without_model_validation(self):
        for duration in (0, -1):
            with self.subTest(duration=duration):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    create_service(duration_minutes=duration)

    def test_database_rejects_negative_price_without_model_validation(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_service(price=Decimal("-0.01"))

    def test_required_fields_are_validated(self):
        with self.assertRaises(ValidationError) as error:
            Service().full_clean()
        self.assertTrue({"name", "duration_minutes", "price"} <= error.exception.message_dict.keys())


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"img", "script"} and "src" in attributes:
            self.urls.append(attributes["src"])
        if tag == "link" and "href" in attributes:
            self.urls.append(attributes["href"])


class HomepageTests(TestCase):
    def test_public_homepage_displays_only_active_services_in_menu_order(self):
        last = create_service(name="Zulu service", display_order=2)
        first = create_service(name="Alpha service", display_order=1)
        second = create_service(name="Beta service", display_order=1)
        inactive = create_service(name="Hidden service", is_active=False, display_order=0)

        response = self.client.get(reverse("catalogue:home"), {"lang": "en"})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.index(first.name), content.index(second.name))
        self.assertLess(content.index(second.name), content.index(last.name))
        self.assertNotContains(response, inactive.name)

    def test_service_name_description_price_and_average_duration_are_visible(self):
        service = create_service()
        response = self.client.get(reverse("catalogue:home"), {"lang": "en"})

        self.assertContains(response, service.name)
        self.assertContains(response, service.description)
        self.assertContains(response, "23.50")
        self.assertContains(response, "35 min")
        self.assertContains(response, "average")
        self.assertContains(response, "EUR")

    def test_service_content_is_escaped(self):
        service = create_service(
            name='<script>alert("name")</script>',
            description='<img src=x onerror="alert(1)">',
        )
        response = self.client.get(reverse("catalogue:home"), {"lang": "en"})

        self.assertContains(response, escape(service.name))
        self.assertContains(response, escape(service.description))
        self.assertNotContains(response, service.name)
        self.assertNotContains(response, service.description)

    def test_empty_catalogue_has_readable_message(self):
        response = self.client.get(reverse("catalogue:home"), {"lang": "en"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Our service menu is being prepared")

    def test_referenced_static_assets_resolve_and_images_use_resources(self):
        response = self.client.get(reverse("catalogue:home"))
        parser = AssetParser()
        parser.feed(response.content.decode())
        static_urls = [url for url in parser.urls if url.startswith(settings.STATIC_URL)]
        self.assertTrue(static_urls)
        image_count = 0
        for url in static_urls:
            with self.subTest(url=url):
                asset_name = url[len(settings.STATIC_URL):]
                # Match Django's static handler, including Windows path separators.
                asset_path = finders.find(url2pathname(asset_name))
                self.assertIsNotNone(asset_path)
                if asset_name.startswith("images/"):
                    image_count += 1
                    self.assertTrue(Path(asset_path).resolve().is_relative_to(settings.BASE_DIR / "resources" / "images"))
        self.assertGreater(image_count, 0)


class HomepageLanguageTests(TestCase):
    def test_header_language_links_identify_current_selection(self):
        for language, other in (("bg", "en"), ("en", "bg")):
            with self.subTest(language=language):
                response = self.client.get(reverse("catalogue:home"), {"lang": language})
                header = response.content.decode().split("</header>")[0]
                labels = {"bg": "Български", "en": "English"}
                self.assertInHTML(
                    f'<a href="?lang={language}" lang="{language}" '
                    f'aria-label="{labels[language]}" aria-current="true">{language.upper()}</a>',
                    header,
                )
                self.assertInHTML(
                    f'<a href="?lang={other}" lang="{other}" '
                    f'aria-label="{labels[other]}">{other.upper()}</a>',
                    header,
                )

    def test_bulgarian_is_default_and_translates_service_content(self):
        service = create_service(
            name_bg="Тестово подстригване",
            description_bg="Описание на тестова услуга.",
        )
        response = self.client.get(reverse("catalogue:home"))
        self.assertContains(response, '<html lang="bg">')
        self.assertContains(response, "Alan Barberhouse")
        self.assertContains(response, service.name_bg)
        self.assertContains(response, service.description_bg)
        self.assertNotContains(response, service.name)
        self.assertNotContains(response, service.description)
        self.assertContains(response, "Вижте услугите")
        self.assertContains(response, "35 мин")
        self.assertContains(response, "средно")

    def test_empty_bulgarian_catalogue_has_translated_message(self):
        response = self.client.get(reverse("catalogue:home"))
        self.assertContains(response, "Подготвяме менюто с услуги")

    def test_english_selection_persists_and_can_switch_back_to_bulgarian(self):
        service = create_service(name_bg="Тестово подстригване")
        response = self.client.get(reverse("catalogue:home"), {"lang": "en"})
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, service.name)
        self.assertNotContains(response, service.name_bg)
        response = self.client.get(reverse("catalogue:home"))
        self.assertContains(response, '<html lang="en">')
        response = self.client.get(reverse("catalogue:home"), {"lang": "bg"})
        self.assertContains(response, '<html lang="bg">')
        self.assertContains(response, service.name_bg)

    def test_unknown_language_uses_default_or_previous_valid_selection(self):
        response = self.client.get(reverse("catalogue:home"), {"lang": "unknown"})
        self.assertContains(response, '<html lang="bg">')
        self.client.get(reverse("catalogue:home"), {"lang": "en"})
        response = self.client.get(reverse("catalogue:home"), {"lang": "<script>"})
        self.assertContains(response, '<html lang="en">')
        self.assertNotContains(response, "<script>")

    def test_missing_bulgarian_fields_fall_back_individually(self):
        translated_name = create_service(name_bg="Само преведено име")
        translated_description = create_service(
            name="Second test service", description="Second English description",
            description_bg="Само преведено описание",
        )
        response = self.client.get(reverse("catalogue:home"))
        self.assertContains(response, translated_name.name_bg)
        self.assertContains(response, translated_name.description)
        self.assertContains(response, translated_description.name)
        self.assertContains(response, translated_description.description_bg)

    def test_bulgarian_content_is_escaped(self):
        service = create_service(
            name_bg='<script>alert("bg")</script>',
            description_bg='<img src=x onerror="alert(2)">',
        )
        response = self.client.get(reverse("catalogue:home"))
        self.assertContains(response, escape(service.name_bg))
        self.assertContains(response, escape(service.description_bg))
        self.assertNotContains(response, service.name_bg)
        self.assertNotContains(response, service.description_bg)


class DemoServicesTests(TestCase):
    def test_seed_creates_valid_demo_menu_and_is_idempotent(self):
        call_command("seed_demo_services", stdout=StringIO())
        initial = list(Service.objects.values())
        self.assertEqual(len(initial), 6)
        for service in Service.objects.all():
            service.full_clean()
            self.assertTrue(service.name_bg)
            self.assertTrue(service.description_bg)

        call_command("seed_demo_services", stdout=StringIO())

        self.assertEqual(list(Service.objects.values()), initial)

    def test_seed_preserves_existing_service_edits_and_custom_services(self):
        call_command("seed_demo_services", stdout=StringIO())
        service = Service.objects.get(name="Signature haircut")
        service.description = "Shop-confirmed description"
        service.name_bg = "Редактирано име"
        service.description_bg = "Редактирано описание"
        service.duration_minutes = 55
        service.price = Decimal("31.25")
        service.is_active = False
        service.display_order = 99
        service.save()
        custom = create_service(name="Custom service")
        before = list(Service.objects.values())

        call_command("seed_demo_services", stdout=StringIO())

        self.assertEqual(list(Service.objects.values()), before)
        self.assertTrue(Service.objects.filter(pk=custom.pk).exists())


class ServiceAdminTests(TestCase):
    def test_anonymous_users_are_redirected_to_login(self):
        url = reverse("admin:catalogue_service_changelist")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('admin:login')}?next={url}")

    def test_staff_without_service_permissions_cannot_manage_services(self):
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.client.force_login(staff)
        service = create_service()
        for url in (
            reverse("admin:catalogue_service_changelist"),
            reverse("admin:catalogue_service_add"),
            reverse("admin:catalogue_service_change", args=[service.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_superuser_can_create_and_edit_service(self):
        administrator = get_user_model().objects.create_superuser(username="admin", password="synthetic-test-password")
        self.client.force_login(administrator)
        fields = {
            "name": "Admin-created service", "description": "Managed menu entry",
            "duration_minutes": 40, "price": "29.95", "is_active": "on", "display_order": 2,
        }
        response = self.client.post(reverse("admin:catalogue_service_add"), fields)
        self.assertEqual(response.status_code, 302)
        service = Service.objects.get(name=fields["name"])
        fields.update(price="30.50", duration_minutes=45)
        response = self.client.post(reverse("admin:catalogue_service_change", args=[service.pk]), fields)
        self.assertEqual(response.status_code, 302)
        service.refresh_from_db()
        self.assertEqual(service.price, Decimal("30.50"))
        self.assertEqual(service.duration_minutes, 45)
