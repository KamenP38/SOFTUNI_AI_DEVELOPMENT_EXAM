"""All booking and schedule mutations serialize on the same barber row."""
import re
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from catalogue.models import Service
from .models import Appointment, Barber, DayOff, WorkingHours

SOFIA = ZoneInfo("Europe/Sofia")


def normalize_phone(value):
    value = re.sub(r"[\s().-]", "", value)
    if not re.fullmatch(r"\+?[0-9]{8,15}", value):
        raise ValidationError("Enter 8–15 digits, optionally starting with +. / Въведете 8–15 цифри, по избор с +.")
    return value


def local_datetime(day, clock):
    """Skip nonexistent/ambiguous DST wall times rather than booking them twice."""
    value = datetime.combine(day, clock, tzinfo=SOFIA)
    restored = value.astimezone(datetime_timezone.utc).astimezone(SOFIA)
    if restored.replace(tzinfo=None) != value.replace(tzinfo=None):
        return None
    if value.replace(fold=0).utcoffset() != value.replace(fold=1).utcoffset():
        return None
    return value


def fits_shift(start, end, shifts, days_off):
    start, end = start.astimezone(SOFIA), end.astimezone(SOFIA)
    shift = shifts.get(start.weekday())
    return bool(
        shift
        and start.date() == end.date()
        and start.date() not in days_off
        and start.time() >= shift[0]
        and end.time() <= shift[1]
    )


def available_slots(barber, service, day, now=None):
    now = now or timezone.now()
    today = now.astimezone(SOFIA).date()
    if not today <= day <= today + timedelta(days=28):
        return []
    eligible = (
        barber.is_active
        and barber.user.is_active
        and service.is_active
        and barber.services.filter(pk=service.pk).exists()
    )
    if not eligible:
        return []
    shift = barber.working_hours.filter(weekday=day.weekday()).first()
    if not shift or barber.days_off.filter(date=day).exists():
        return []
    opening = datetime.combine(day, shift.opens_at)
    cursor = opening.replace(second=0, microsecond=0)
    minutes = (15 - cursor.minute % 15) % 15
    cursor += timedelta(minutes=minutes)
    if cursor < opening:
        cursor += timedelta(minutes=15)
    closing = datetime.combine(day, shift.closes_at)
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=SOFIA)
    day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=SOFIA)
    appointments = list(
        barber.appointments.filter(
            cancelled_at__isnull=True,
            starts_at__lt=day_end,
            ends_at__gt=day_start,
        )
    )
    slots = []
    while cursor < closing:
        start = local_datetime(day, cursor.time())
        if start:
            # Arithmetic in UTC gives the exact elapsed service duration across DST.
            end = (
                start.astimezone(datetime_timezone.utc)
                + timedelta(minutes=service.duration_minutes)
            ).astimezone(SOFIA)
            fits = start > now and end.date() == day and end.time() <= shift.closes_at
            no_overlap = all(
                start >= item.ends_at or end <= item.starts_at for item in appointments
            )
            if fits and no_overlap:
                slots.append(start)
        cursor += timedelta(minutes=15)
    return slots


@transaction.atomic
def reserve(
    *, barber_id, service_id, day, clock, request_id, customer_name, phone, email=""
):
    barber = Barber.objects.select_for_update().select_related("user").get(pk=barber_id)
    existing = Appointment.objects.filter(request_id=request_id).first()
    if existing:
        return existing
    service = Service.objects.get(pk=service_id)
    slots = available_slots(barber, service, day)
    start = next((slot for slot in slots if slot.time() == clock), None)
    if start is None:
        raise ValidationError("This time is no longer available. Choose another. / Часът вече не е свободен. Изберете друг.")
    name = customer_name.strip()
    if not 2 <= len(name) <= 100:
        raise ValidationError("Name must contain 2–100 characters. / Името трябва да е 2–100 знака.")
    appointment = Appointment(
        barber=barber,
        service=service,
        request_id=request_id,
        service_name=service.name,
        service_name_bg=service.name_bg,
        duration_minutes=service.duration_minutes,
        price=service.price,
        starts_at=start,
        ends_at=start.astimezone(datetime_timezone.utc) + timedelta(minutes=service.duration_minutes),
        customer_name=name,
        phone=normalize_phone(phone),
        email=email,
    )
    appointment.full_clean()
    appointment.save()
    return appointment


def validate_schedule(barber, shifts, days_off):
    appointments = barber.appointments.filter(
        cancelled_at__isnull=True, ends_at__gt=timezone.now()
    )
    conflicts = [
        item for item in appointments
        if not fits_shift(item.starts_at, item.ends_at, shifts, days_off)
    ]
    if conflicts:
        times = ", ".join(
            f"{item.starts_at.astimezone(SOFIA):%d.%m.%Y %H:%M}–{item.ends_at.astimezone(SOFIA):%H:%M}"
            for item in conflicts[:10]
        )
        raise ValidationError(
            "Existing appointments conflict with this change. Cancel them first or keep their hours. / "
            "Промяната засяга съществуващи резервации. Първо ги отменете или запазете часовете им: " + times
        )


@transaction.atomic
def replace_hours(barber_id, shifts):
    barber = Barber.objects.select_for_update().get(pk=barber_id)
    for weekday, (opens, closes) in shifts.items():
        if weekday not in range(7) or opens >= closes:
            raise ValidationError("Invalid working hours. / Невалидно работно време.")
    validate_schedule(barber, shifts, set(barber.days_off.values_list("date", flat=True)))
    barber.working_hours.all().delete()
    WorkingHours.objects.bulk_create([
        WorkingHours(barber=barber, weekday=weekday, opens_at=times[0], closes_at=times[1])
        for weekday, times in shifts.items()
    ])


@transaction.atomic
def change_day_off(barber_id, day, remove=False):
    barber = Barber.objects.select_for_update().get(pk=barber_id)
    days_off = set(barber.days_off.values_list("date", flat=True))
    if remove:
        days_off.discard(day)
    else:
        days_off.add(day)
    shifts = {s.weekday: (s.opens_at, s.closes_at) for s in barber.working_hours.all()}
    validate_schedule(barber, shifts, days_off)
    if remove:
        barber.days_off.filter(date=day).delete()
    else:
        DayOff.objects.get_or_create(barber=barber, date=day)


@transaction.atomic
def cancel_appointment(appointment, future_only=False):
    Barber.objects.select_for_update().get(pk=appointment.barber_id)
    appointment.refresh_from_db()
    if appointment.cancelled_at:
        return
    if future_only and appointment.starts_at <= timezone.now():
        raise ValidationError("Only future appointments can be cancelled. / Може да отмените само бъдещи часове.")
    appointment.cancelled_at = timezone.now()
    appointment.save(update_fields=["cancelled_at"])
