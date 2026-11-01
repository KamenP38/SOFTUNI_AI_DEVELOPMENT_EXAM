"""Update only untouched original demo rows; never seed a fresh database."""

from django.db import migrations


SERVICE_UPDATES = [
    (
        {
            "name": "Signature haircut",
            "name_bg": "Класическо подстригване",
            "description": "A considered cut, shaped to suit you. Finished with a wash and style.",
            "description_bg": "Прецизно подстригване, съобразено с вас, с измиване и оформяне.",
            "duration_minutes": 40,
            "price": "25.00",
            "is_active": True,
            "display_order": 1,
        },
        {
            "name": "Classic Haircut",
            "name_bg": "Класическо подстригване",
            "description": "A timeless cut tailored to your face shape and style. Includes wash, cut and finish.",
            "description_bg": "Вечен стил, съобразен с формата на лицето ви. Включва измиване, подстригване и финиширане.",
            "duration_minutes": 30,
            "price": "20.00",
            "is_active": True,
            "display_order": 1,
        },
    ),
    (
        {
            "name": "Skin fade",
            "name_bg": "Скин фейд",
            "description": "A seamless fade with clean edges and a carefully styled finish.",
            "description_bg": "Плавен преход, изчистени контури и внимателно оформен завършек.",
            "duration_minutes": 45,
            "price": "28.00",
            "is_active": True,
            "display_order": 2,
        },
        {
            "name": "Fade & Taper",
            "name_bg": "Фейд & Тейпър",
            "description": "Skin fade, low fade or mid fade — executed with surgical precision by our barbers.",
            "description_bg": "Skin fade, нисък или среден фейд — изпълнен с хирургическа прецизност.",
            "duration_minutes": 45,
            "price": "25.00",
            "is_active": True,
            "display_order": 3,
        },
    ),
    (
        {
            "name": "Beard sculpting",
            "name_bg": "Оформяне на брада",
            "description": "Shape, definition and a tidy finish, tailored to your beard.",
            "description_bg": "Форма, ясни контури и спретнат завършек, съобразени с вашата брада.",
            "duration_minutes": 25,
            "price": "18.00",
            "is_active": True,
            "display_order": 3,
        },
        {
            "name": "Beard Trim & Shape",
            "name_bg": "Оформяне на брада",
            "description": "Precision beard grooming to define your look. Sculpted edges, clean lines.",
            "description_bg": "Прецизно оформяне на брадата за дефиниран вид. Чисти линии и ясни контури.",
            "duration_minutes": 30,
            "price": "15.00",
            "is_active": True,
            "display_order": 2,
        },
    ),
    (
        {
            "name": "Haircut & beard",
            "name_bg": "Подстригване и брада",
            "description": "The full refresh. A signature haircut paired with beard shaping.",
            "description_bg": "Цялостно освежаване: класическо подстригване и оформяне на брадата.",
            "duration_minutes": 60,
            "price": "38.00",
            "is_active": True,
            "display_order": 4,
        },
        {
            "name": "Cut & Beard Combo",
            "name_bg": "Подстригване + Брада",
            "description": "The complete package. Haircut + beard trim together for the full gentleman look.",
            "description_bg": "Пълният пакет. Подстригване и оформяне на брада — за истинския джентълменски вид.",
            "duration_minutes": 60,
            "price": "35.00",
            "is_active": True,
            "display_order": 5,
        },
    ),
    (
        {
            "name": "Traditional shave",
            "name_bg": "Класическо бръснене",
            "description": "A close shave with a warm towel and a soothing finish.",
            "description_bg": "Гладко бръснене с топла кърпа и успокояваща финална грижа.",
            "duration_minutes": 30,
            "price": "22.00",
            "is_active": True,
            "display_order": 5,
        },
        {
            "name": "Hot Towel Shave",
            "name_bg": "Бръснене с гореща кърпа",
            "description": "The full traditional experience. Hot towel, straight razor, premium shaving cream.",
            "description_bg": "Пълното традиционно изживяване. Гореща кърпа, бръснач и първокласен крем.",
            "duration_minutes": 30,
            "price": "25.00",
            "is_active": True,
            "display_order": 4,
        },
    ),
    (
        {
            "name": "Scalp & hair treatment",
            "name_bg": "Грижа за косата и скалпа",
            "description": "A little extra care: a cleansing wash, scalp massage and conditioning.",
            "description_bg": "Допълнителна грижа с измиване, масаж на скалпа и подхранване.",
            "duration_minutes": 20,
            "price": "15.00",
            "is_active": True,
            "display_order": 6,
        },
        {
            "name": "Kids Cut",
            "name_bg": "Детско подстригване",
            "description": "Patient, friendly service for the little ones. Ages 3–12 welcome.",
            "description_bg": "Търпелива и приятелска услуга за малчуганите. Приемаме деца от 3 до 12 години.",
            "duration_minutes": 30,
            "price": "15.00",
            "is_active": True,
            "display_order": 6,
        },
    ),
]


def update_matching_services(apps, schema_editor, reverse=False):
    services = apps.get_model("catalogue", "Service").objects.using(schema_editor.connection.alias)
    for old, new in SERVICE_UPDATES:
        source, target = (new, old) if reverse else (old, new)
        # Any edit, inactive state or target-name collision preserves the existing row.
        if not services.filter(name=target["name"]).exists():
            services.filter(**source).update(**target)


def forwards(apps, schema_editor):
    update_matching_services(apps, schema_editor)


def backwards(apps, schema_editor):
    update_matching_services(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0002_service_description_bg_service_name_bg")]
    operations = [migrations.RunPython(forwards, backwards)]
