from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogue.models import Service

DEMO_SERVICES = [
    (
        "Signature haircut",
        "A considered cut, shaped to suit you. Finished with a wash and style.",
        40,
        "25.00",
    ),
    (
        "Skin fade",
        "A seamless fade with clean edges and a carefully styled finish.",
        45,
        "28.00",
    ),
    (
        "Beard sculpting",
        "Shape, definition and a tidy finish, tailored to your beard.",
        25,
        "18.00",
    ),
    (
        "Haircut & beard",
        "The full refresh. A signature haircut paired with beard shaping.",
        60,
        "38.00",
    ),
    (
        "Traditional shave",
        "A close shave with a warm towel and a soothing finish.",
        30,
        "22.00",
    ),
    (
        "Scalp & hair treatment",
        "A little extra care: a cleansing wash, scalp massage and conditioning.",
        20,
        "15.00",
    ),
]

DEMO_TRANSLATIONS = {
    "Signature haircut": (
        "Класическо подстригване",
        "Прецизно подстригване, съобразено с вас, с измиване и оформяне.",
    ),
    "Skin fade": (
        "Скин фейд",
        "Плавен преход, изчистени контури и внимателно оформен завършек.",
    ),
    "Beard sculpting": (
        "Оформяне на брада",
        "Форма, ясни контури и спретнат завършек, съобразени с вашата брада.",
    ),
    "Haircut & beard": (
        "Подстригване и брада",
        "Цялостно освежаване: класическо подстригване и оформяне на брадата.",
    ),
    "Traditional shave": (
        "Класическо бръснене",
        "Гладко бръснене с топла кърпа и успокояваща финална грижа.",
    ),
    "Scalp & hair treatment": (
        "Грижа за косата и скалпа",
        "Допълнителна грижа с измиване, масаж на скалпа и подхранване.",
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
