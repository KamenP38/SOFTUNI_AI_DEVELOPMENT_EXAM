"""All booking and schedule mutations serialize on the same barber row."""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from catalogue.models import Service
from .models import Appointment, Barber, DayOff, WorkingHours

SOFIA = ZoneInfo("Europe/Sofia")
MAX_DAYS_OFF = 366
PHONE_ERROR = (
    "Enter 0 or +359 followed by exactly 9 digits (0–9), without spaces or separators, "
    "e.g. 0888123456 or +359888123456. / "
    "Въведете 0 или +359, следвани от точно 9 цифри (0–9), без интервали или разделители, "
    "например 0888123456 или +359888123456."
)


def normalize_phone(value):
    value = value.strip()
    if not re.fullmatch(r"(?:0|\+359)[0-9]{9}", value):
        raise ValidationError(PHONE_ERROR)
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


def slots_for_shift(service, day, shift, appointments, now):
    """Shared slot calculation; appointments contain only (start, end) pairs."""
    today = now.astimezone(SOFIA).date()
    if not shift or not today <= day <= today + timedelta(days=28):
        return []
    opening = datetime.combine(day, shift.opens_at)
    cursor = opening.replace(second=0, microsecond=0)
    minutes = (15 - cursor.minute % 15) % 15
    cursor += timedelta(minutes=minutes)
    if cursor < opening:
        cursor += timedelta(minutes=15)
    closing = datetime.combine(day, shift.closes_at)
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
                start >= booked_end or end <= booked_start
                for booked_start, booked_end in appointments
            )
            if fits and no_overlap:
                slots.append(start)
        cursor += timedelta(minutes=15)
    return slots


def available_slots(barber, service, day, now=None):
    """Read current availability, including inside the reservation transaction."""
    now = now or timezone.now()
    today = now.astimezone(SOFIA).date()
    if not today <= day <= today + timedelta(days=28):
        return []
    if not (
        barber.is_active and barber.user.is_active and service.is_active
        and barber.services.filter(pk=service.pk).exists()
    ):
        return []
    shift = barber.working_hours.filter(weekday=day.weekday()).first()
    if not shift or barber.days_off.filter(date=day).exists():
        return []
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=SOFIA)
    day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=SOFIA)
    appointments = list(barber.appointments.filter(
        cancelled_at__isnull=True, starts_at__lt=day_end, ends_at__gt=day_start,
    ).values_list("starts_at", "ends_at"))
    return slots_for_shift(service, day, shift, appointments, now)


class AvailabilitySnapshot:
    """Request-local public inventory, loaded in six queries regardless of team size.

    Only anonymous appointment intervals are read. The snapshot is never reused by
    reserve(), which rechecks current availability under the barber row lock.
    """

    def __init__(self, now=None):
        self.now = now or timezone.now()
        today = self.now.astimezone(SOFIA).date()
        self.dates = [today + timedelta(days=offset) for offset in range(29)]
        self.services = list(Service.objects.filter(is_active=True))
        self.barbers = list(Barber.objects.filter(
            is_active=True, user__is_active=True,
        ).prefetch_related(
            Prefetch("services", queryset=Service.objects.filter(is_active=True)),
            "working_hours",
            Prefetch("days_off", queryset=DayOff.objects.filter(
                date__gte=today, date__lte=self.dates[-1],
            )),
        ))
        start = datetime.combine(today, datetime.min.time(), tzinfo=SOFIA)
        end = datetime.combine(self.dates[-1] + timedelta(days=1), datetime.min.time(), tzinfo=SOFIA)
        intervals = defaultdict(list)
        for barber_id, booked_start, booked_end in Appointment.objects.filter(
            barber_id__in=[barber.pk for barber in self.barbers],
            cancelled_at__isnull=True, starts_at__lt=end, ends_at__gt=start,
        ).values_list("barber_id", "starts_at", "ends_at"):
            # Include cross-midnight bookings on every day they overlap.
            for day in self.dates:
                day_start = datetime.combine(day, datetime.min.time(), tzinfo=SOFIA)
                day_end = day_start + timedelta(days=1)
                if booked_start < day_end and booked_end > day_start:
                    intervals[(barber_id, day)].append((booked_start, booked_end))
        self.slots = {}
        for barber in self.barbers:
            shifts = {shift.weekday: shift for shift in barber.working_hours.all()}
            days_off = {off.date for off in barber.days_off.all()}
            for service in barber.services.all():
                for day in self.dates:
                    shift = None if day in days_off else shifts.get(day.weekday())
                    slots = slots_for_shift(service, day, shift, intervals[(barber.pk, day)], self.now)
                    if slots:
                        self.slots[(str(service.pk), str(barber.pk), day.isoformat())] = slots

    def matching_choices(self, values):
        """Each field depends on the other two, never on its own current value."""
        fields = ("service", "barber", "date")
        choices = {field: set() for field in fields}
        matches = False
        for key in self.slots:
            compatible = [not values[field] or values[field] == value for field, value in zip(fields, key)]
            matches = matches or all(compatible)
            for index, field in enumerate(fields):
                if all(compatible[other] for other in range(3) if other != index):
                    choices[field].add(key[index])
        return choices, matches


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


def day_off_dates(start_date, end_date=None):
    """Validate and expand a bounded inclusive range for forms and direct callers."""
    end_date = start_date if end_date is None else end_date
    if any(not isinstance(day, date) or isinstance(day, datetime) for day in (start_date, end_date)):
        raise ValidationError("Enter valid dates. / Въведете валидни дати.")
    if end_date < start_date:
        raise ValidationError(
            "End date must be on or after start date. / "
            "Крайната дата трябва да е на или след началната дата."
        )
    day_count = (end_date - start_date).days + 1
    if day_count > MAX_DAYS_OFF:
        raise ValidationError(
            "Choose at most 366 days, including both dates. / "
            "Изберете най-много 366 дни, включително двете дати."
        )
    return {start_date + timedelta(days=offset) for offset in range(day_count)}


def add_days_off(barber_id, start_date, end_date=None):
    """Add all dates together, retaining any days off already in the range."""
    _change_days_off(barber_id, day_off_dates(start_date, end_date))


def change_day_off(barber_id, day, remove=False):
    """Keep the single-day add/remove interface on the same locked mutation path."""
    _change_days_off(barber_id, day_off_dates(day), remove=remove)


@transaction.atomic
def _change_days_off(barber_id, dates, remove=False):
    barber = Barber.objects.select_for_update().get(pk=barber_id)
    existing = set(barber.days_off.values_list("date", flat=True))
    days_off = existing - dates if remove else existing | dates
    shifts = {s.weekday: (s.opens_at, s.closes_at) for s in barber.working_hours.all()}
    # Validate the complete proposal under the booking lock before writing any date.
    validate_schedule(barber, shifts, days_off)
    if remove:
        barber.days_off.filter(date__in=dates).delete()
    else:
        DayOff.objects.bulk_create([
            DayOff(barber=barber, date=day) for day in sorted(dates - existing)
        ])


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
