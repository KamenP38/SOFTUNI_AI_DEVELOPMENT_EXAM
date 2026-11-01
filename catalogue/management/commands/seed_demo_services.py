from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogue.models import Service

DEMO_SERVICES = [
    (
        "Classic Haircut",
        "A timeless cut tailored to your face shape and style. Includes wash, cut and finish.",
        30,
        "20.00",
    ),
    (
        "Beard Trim & Shape",
        "Precision beard grooming to define your look. Sculpted edges, clean lines.",
        30,
        "15.00",
    ),
    (
        "Fade & Taper",
        "Skin fade, low fade or mid fade — executed with surgical precision by our barbers.",
        45,
        "25.00",
    ),
    (
        "Hot Towel Shave",
        "The full traditional experience. Hot towel, straight razor, premium shaving cream.",
        30,
        "25.00",
    ),
    (
        "Cut & Beard Combo",
        "The complete package. Haircut + beard trim together for the full gentleman look.",
        60,
        "35.00",
    ),
    (
        "Kids Cut",
        "Patient, friendly service for the little ones. Ages 3–12 welcome.",
        30,
        "15.00",
    ),
]

DEMO_TRANSLATIONS = {
    "Classic Haircut": (
        "Класическо подстригване",
        "Вечен стил, съобразен с формата на лицето ви. Включва измиване, подстригване и финиширане.",
    ),
    "Beard Trim & Shape": (
        "Оформяне на брада",
        "Прецизно оформяне на брадата за дефиниран вид. Чисти линии и ясни контури.",
    ),
    "Fade & Taper": (
        "Фейд & Тейпър",
        "Skin fade, нисък или среден фейд — изпълнен с хирургическа прецизност.",
    ),
    "Hot Towel Shave": (
        "Бръснене с гореща кърпа",
        "Пълното традиционно изживяване. Гореща кърпа, бръснач и първокласен крем.",
    ),
    "Cut & Beard Combo": (
        "Подстригване + Брада",
        "Пълният пакет. Подстригване и оформяне на брада — за истинския джентълменски вид.",
    ),
    "Kids Cut": (
        "Детско подстригване",
        "Търпелива и приятелска услуга за малчуганите. Приемаме деца от 3 до 12 години.",
    ),
}


class Command(BaseCommand):
    help = "Add illustrative EUR services for local preview; preserve existing entries."

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0
        for index, (name, description, duration, price) in enumerate(DEMO_SERVICES, 1):
            _, created = Service.objects.get_or_create(
                name=name,
                defaults={
                    "name_bg": DEMO_TRANSLATIONS[name][0],
                    "description_bg": DEMO_TRANSLATIONS[name][1],
                    "description": description,
                    "duration_minutes": duration,
                    "price": Decimal(price),
                    "display_order": index,
                },
            )
            created_count += created
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created_count} demo services; existing entries unchanged."
            )
        )
