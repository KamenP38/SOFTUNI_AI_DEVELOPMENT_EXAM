"""Guarded, command-line-only synthetic fixtures and database observations."""
import json
import os
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

os.environ["DJANGO_SETTINGS_MODULE"] = "cypress_audit.settings"
import django
django.setup()

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.utils import timezone
from booking.models import Appointment, Barber, DayOff, ShopManager, WorkingHours
from catalogue.models import Service

PASSWORD = "Synthetic-Audit-Only!492"


def guard():
    expected = (Path(__file__).resolve().parent.parent / ".artifacts" / "cypress-audit.sqlite3").resolve()
    actual = Path(connection.settings_dict["NAME"]).resolve()
    if actual != expected or settings.SETTINGS_MODULE != "cypress_audit.settings":
        raise RuntimeError("Refusing to access anything except the isolated Cypress database")
    expected.parent.mkdir(exist_ok=True)


def reset():
    cache.clear()
    call_command("flush", interactive=False, verbosity=0)
    users = {}
    for role in ("owner", "alan", "boris", "inactive", "outsider"):
        users[role] = get_user_model().objects.create_user(role, password=PASSWORD)
    ShopManager.objects.create(user=users["owner"])
    cut = Service.objects.create(name="Audit Haircut", name_bg="Тестово подстригване", duration_minutes=30, price="20.00")
    beard = Service.objects.create(name="Audit Beard", name_bg="Тестова брада", duration_minutes=15, price="10.00", display_order=1)
    inactive = Service.objects.create(name="Inactive Service", duration_minutes=30, price="5.00", is_active=False)
    alan = Barber.objects.create(user=users["alan"], name="Audit Alan")
    boris = Barber.objects.create(user=users["boris"], name="Audit Boris")
    disabled = Barber.objects.create(user=users["inactive"], name="Inactive Barber", is_active=False)
    alan.services.set([cut, beard, inactive])
    boris.services.set([cut])
    disabled.services.set([cut])
    for barber in (alan, boris, disabled):
        for weekday in range(7):
            WorkingHours.objects.create(barber=barber, weekday=weekday, opens_at=time(9), closes_at=time(17))
    day = timezone.localdate() + timedelta(days=2)
    appointments = {}
    for barber, role in ((alan, "alan"), (boris, "boris")):
        start = timezone.make_aware(datetime.combine(day, time(12)))
        appointment = Appointment.objects.create(
            request_id=uuid.uuid4(), barber=barber, service=cut,
            service_name=cut.name, service_name_bg=cut.name_bg,
            duration_minutes=30, price=cut.price, starts_at=start,
            ends_at=start + timedelta(minutes=30), customer_name=f"Synthetic {role} client",
            phone="+359888000001" if role == "alan" else "+359888000002",
            email=f"{role}@example.invalid",
        )
        appointments[role] = {"id": appointment.pk, "reference": str(appointment.reference)}
    DayOff.objects.create(barber=boris, date=day + timedelta(days=1))
    return {
        "date": day.isoformat(), "nextDate": (day + timedelta(days=1)).isoformat(),
        "laterDate": (day + timedelta(days=4)).isoformat(),
        "weekday": day.weekday(),
        "barbers": {"alan": alan.pk, "boris": boris.pk, "inactive": disabled.pk},
        "services": {"cut": cut.pk, "beard": beard.pk, "inactive": inactive.pk},
        "appointments": appointments,
    }


def snapshot():
    models = {"appointments": Appointment, "barbers": Barber, "services": Service,
              "hours": WorkingHours, "daysOff": DayOff, "assignments": Barber.services.through,
              "managers": ShopManager}
    result = {key: list(model.objects.order_by("pk").values()) for key, model in models.items()}
    result["users"] = list(get_user_model().objects.order_by("pk").values(
        "id", "username", "password", "is_active", "is_staff", "is_superuser",
        "first_name", "last_name", "email", "date_joined"))
    return result


def exam_presentation():
    """Relabel the already-reset synthetic rows for the exam walkthrough only."""
    Service.objects.filter(name="Audit Haircut").update(
        name="Classic Haircut", description="A tailored cut, finished and styled.")
    Service.objects.filter(name="Audit Beard").update(
        name="Beard Trim", description="Clean lines and a carefully shaped beard.")
    Barber.objects.filter(user__username="alan").update(name="Demo Alan")
    Barber.objects.filter(user__username="boris").update(name="Demo Boris")
    Appointment.objects.filter(barber__user__username="alan").update(
        customer_name="Demo Daniel", service_name="Classic Haircut")
    Appointment.objects.filter(barber__user__username="boris").update(
        customer_name="Demo Martin", service_name="Classic Haircut")
    return True


def session(role):
    if role not in {"owner", "alan", "boris", "inactive", "outsider"}:
        raise ValueError("Unknown synthetic role")
    client = Client()
    client.force_login(get_user_model().objects.get(username=role))
    return client.cookies[settings.SESSION_COOKIE_NAME].value


if __name__ == "__main__":
    guard()
    action = sys.argv[1]
    payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    if action == "migrate":
        call_command("migrate", interactive=False, verbosity=0)
        result = True
    elif action == "reset":
        result = reset()
    elif action == "snapshot":
        result = snapshot()
    elif action == "exam_presentation":
        result = exam_presentation()
    elif action == "session":
        result = session(payload)
    elif action == "change_quote":
        service = Service.objects.get(name="Audit Haircut")
        service.price = "35.00"
        service.duration_minutes = 45
        service.save()
        result = True
    elif action == "occupy_slot":
        from booking.rules import reserve
        appointment = reserve(
            barber_id=Barber.objects.get(user__username="alan").pk,
            service_id=Service.objects.get(name="Audit Haircut").pk,
            day=timezone.localdate() + timedelta(days=2), clock=time(9),
            request_id=uuid.uuid4(), customer_name="Synthetic Competing Client",
            phone="0888000003", email="competing@example.invalid",
        )
        result = appointment.pk
    else:
        raise ValueError("Unknown audit action")
    print(json.dumps(result, default=str))
