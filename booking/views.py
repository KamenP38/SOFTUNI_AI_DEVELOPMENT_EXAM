import hashlib
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.debug import sensitive_post_parameters

from catalogue.models import Service
from .forms import BarberForm, BookingForm, DayOffForm, DayOffRangeForm, HoursForm, MyServicesForm, SelectionForm, ServiceForm
from .models import Appointment, Barber
from .permissions import active_barber, is_owner, require_edit, require_owner, staff_required
from .rules import SOFIA, AvailabilitySnapshot, add_days_off, cancel_appointment, change_day_off, replace_hours, reserve


def language_for(request):
    language = request.GET.get("lang", request.session.get("language", "bg"))
    if language not in ("bg", "en"):
        language = request.session.get("language", "bg")
    if language not in ("bg", "en"):
        language = "bg"
    request.session["language"] = language
    translation.activate(language)
    return language


def page(request, template, context=None, status=200):
    context = dict(context or {})
    context.update(language=language_for(request), shop_name=settings.SHOP_NAME,
                   owner=is_owner(request.user), staff_barber=active_barber(request.user))
    response = render(request, f"booking/{template}.html", context, status=status)
    response["Referrer-Policy"] = "same-origin"
    return response


def remember(session, key, value):
    values = session.get(key, [])
    session[key] = ([item for item in values if item != str(value)] + [str(value)])[-30:]


def throttled(request, scope, limit, seconds=900):
    # Trust REMOTE_ADDR only; a client-supplied forwarding header cannot bypass this.
    address = request.META.get("REMOTE_ADDR", "unknown")
    digest = hashlib.sha256(address.encode()).hexdigest()
    key = f"booking:{scope}:{digest}"
    if cache.add(key, 1, seconds):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, seconds)
        return False


def rate_response(request):
    response = page(request, "message", {"message": "Too many attempts. Please try again later. / Твърде много опити. Опитайте по-късно."}, status=429)
    response["Retry-After"] = "900"
    return response


@never_cache
@require_http_methods(["GET", "POST"])
def book(request):
    language = language_for(request)
    form, slots, selected = None, [], None
    if request.method == "POST":
        # Replay authorized requests before validating mutable catalogue/availability.
        try:
            token = uuid.UUID(request.POST.get("request_id", ""))
        except (ValueError, TypeError, AttributeError):
            token = None
        if token and str(token) in request.session.get("booking_requests", []):
            existing = Appointment.objects.filter(request_id=token).first()
            if existing:
                remember(request.session, "booking_references", existing.reference)
                return redirect("booking:confirmation", reference=existing.reference)
        form = BookingForm(request.POST, language=language)
        if form.is_valid():
            data = form.cleaned_data
            if str(data["request_id"]) not in request.session.get("booking_requests", []):
                raise PermissionDenied
            if throttled(request, "reserve", 30):
                return rate_response(request)
            try:
                appointment = reserve(barber_id=data["barber"].pk, service_id=data["service"].pk,
                    day=data["date"], clock=data["time"], request_id=data["request_id"],
                    customer_name=data["customer_name"], phone=data["phone"], email=data["email"])
            except (ValidationError, IntegrityError, OperationalError) as error:
                form.add_error(None, error if isinstance(error, ValidationError) else
                    "This slot could not be reserved. Refresh available times and try again. / Не успяхме да запазим часа. Обновете свободните часове и опитайте отново.")
            else:
                remember(request.session, "booking_references", appointment.reference)
                return redirect("booking:confirmation", reference=appointment.reference)
    # Build after a failed POST too: a transaction conflict must refresh options.
    availability = AvailabilitySnapshot()
    selection_data = request.POST if request.method == "POST" else request.GET
    selection = SelectionForm(selection_data, language=language, availability=availability)
    if selection.is_valid() and all(selection.cleaned_data.values()):
        selected = selection.cleaned_data
        slots = availability.slots.get((
            str(selected["service"].pk), str(selected["barber"].pk), selected["date"].isoformat(),
        ), [])
        if request.method == "GET" and request.GET.get("time"):
            chosen = next((slot for slot in slots if slot.strftime("%H:%M") == request.GET["time"]), None)
            if chosen:
                token = uuid.uuid4()
                remember(request.session, "booking_requests", token)
                form = BookingForm(language=language, initial={**selection_data.dict(), "request_id": token})
            else:
                selection.add_error(None, "This time is unavailable. / Часът не е свободен.")
    filter_fields = []
    for name in ("service", "barber", "date"):
        remaining = {key: value for key, value in selection.values.items() if key != name and value}
        filter_fields.append({
            "field": selection[name],
            "clear_url": "?" + urlencode({**remaining, "lang": language}) + "#visit-selection",
            "has_value": bool(selection.values[name]),
        })
    return page(request, "book", {
        "selection": selection, "filter_fields": filter_fields,
        "no_matches": not selection.has_matches,
        "form": form, "slots": slots, "selected": selected,
    })


def session_appointment(request, reference):
    if str(reference) not in request.session.get("booking_references", []):
        raise Http404
    return get_object_or_404(Appointment.objects.select_related("barber"), reference=reference)


@never_cache
def confirmation(request, reference):
    appointment = session_appointment(request, reference)
    return page(request, "confirmation", {"appointment": appointment, "can_cancel": not appointment.cancelled_at and appointment.starts_at > timezone.now()})


@never_cache
@require_POST
def customer_cancel(request, reference):
    appointment = session_appointment(request, reference)
    try:
        cancel_appointment(appointment, future_only=True)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect("booking:confirmation", reference=reference)


@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def staff_login(request):
    language_for(request)
    if request.method == "POST" and throttled(request, "login", 20):
        return rate_response(request)
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if is_owner(user) or active_barber(user):
            login(request, user)
            # Fixed destination avoids open redirects and stale external next values.
            return redirect("booking:dashboard")
        form.add_error(None, "This account has no shop access. / Този профил няма достъп до салона.")
    return page(request, "login", {"form": form})


@never_cache
@require_POST
def staff_logout(request):
    logout(request)
    return redirect("catalogue:home")


@never_cache
@staff_required
def dashboard(request):
    barbers = Barber.objects.select_related("user").prefetch_related("services")
    if not request.is_owner:
        barbers = barbers.filter(is_active=True, user__is_active=True)
    barbers = list(barbers)
    for barber in barbers:
        barber.has_active_services = any(service.is_active for service in barber.services.all())
    return page(request, "dashboard", {"barbers": barbers})


@never_cache
@staff_required
def schedule(request):
    language = language_for(request)
    day_form = DayOffForm(request.GET if "date" in request.GET else None,
                         initial={"date": timezone.localdate(timezone=SOFIA)}, language=language)
    day = day_form.cleaned_data["date"] if day_form.is_valid() else timezone.localdate(timezone=SOFIA)
    if not 1900 <= day.year <= 2100:
        day_form.add_error("date", "Choose a date between 1900 and 2100. / Изберете дата между 1900 и 2100 г.")
        day = timezone.localdate(timezone=SOFIA)
    span = 1 if request.GET.get("view") == "day" else 7
    barbers = Barber.objects.select_related("user")
    if not request.is_owner:
        barbers = barbers.filter(is_active=True, user__is_active=True)
    choices = list(barbers)
    barber_id = request.GET.get("barber", "")
    if barber_id.isdigit():
        barbers = barbers.filter(pk=barber_id)
    barbers = list(barbers.prefetch_related("working_hours", "days_off"))
    end_day = day + timedelta(days=span)
    appointments = Appointment.objects.filter(barber__in=barbers,
        starts_at__date__gte=day, starts_at__date__lt=end_day).select_related("barber")
    grouped = {}
    for item in appointments:
        private = request.is_owner or request.barber.pk == item.barber_id
        if item.cancelled_at and not private:
            continue
        key = (item.barber_id, item.starts_at.astimezone(SOFIA).date())
        # Colleagues receive only anonymous time blocks, not customer objects.
        row = {"starts_at": item.starts_at, "ends_at": item.ends_at}
        if private:
            row.update(customer_name=item.customer_name, phone=item.phone, email=item.email,
                       service_name=item.service_name, service_name_bg=item.service_name_bg,
                       price=item.price, pk=item.pk, cancelled_at=item.cancelled_at, private=True)
        grouped.setdefault(key, []).append(row)
    columns = []
    for barber in barbers:
        shifts = {s.weekday: s for s in barber.working_hours.all()}
        off = {d.date for d in barber.days_off.all()}
        days = []
        for offset in range(span):
            date = day + timedelta(days=offset)
            shift = None if date in off else shifts.get(date.weekday())
            days.append({"date": date, "shift": shift, "appointments": grouped.get((barber.pk, date), [])})
        columns.append({"barber": barber, "days": days, "editable": request.is_owner or request.barber.pk == barber.pk})
    return page(request, "schedule", {"columns": columns, "choices": choices, "day_form": day_form,
        "selected_barber": barber_id, "span": span, "previous": day - timedelta(days=span), "next": end_day})


@never_cache
@staff_required
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password", "password_confirm")
def barber_edit(request, pk=None):
    require_owner(request)
    language = language_for(request)
    barber = get_object_or_404(Barber.objects.select_related("user"), pk=pk) if pk else None
    form = BarberForm(request.POST or None, barber=barber, language=language)
    hours = HoursForm(request.POST or None, language=language) if not barber else None
    if request.method == "POST":
        valid = form.is_valid()
        if hours:
            valid = hours.is_valid() and valid
        if valid:
            try:
                barber = form.save(shifts=hours.cleaned_data["shifts"] if hours else None)
            except (ValidationError, IntegrityError) as error:
                form.add_error(None, error if isinstance(error, ValidationError) else "Username already exists. / Името вече съществува.")
            else:
                messages.success(request, "Profile saved. / Профилът е запазен.")
                return redirect("booking:dashboard")
    return page(request, "barber_edit", {"form": form, "hours": hours, "barber": barber})


@never_cache
@staff_required
@require_http_methods(["GET", "POST"])
def my_services(request):
    if not request.barber:
        raise PermissionDenied
    language = language_for(request)
    form = MyServicesForm(
        request.POST if request.method == "POST" else None,
        barber=request.barber, language=language,
    )
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as error:
            form.add_error("services", error)
        else:
            messages.success(request, "Услугите са запазени." if language == "bg" else "Services saved.")
            return redirect("booking:my_services")
    return page(request, "my_services", {"form": form})


@never_cache
@staff_required
@require_http_methods(["GET", "POST"])
def hours_edit(request, pk):
    barber = get_object_or_404(Barber, pk=pk)
    require_edit(request, barber)
    language = language_for(request)
    hours = HoursForm(request.POST if request.POST.get("action") == "hours" else None, barber=barber, language=language)
    off_form = DayOffRangeForm(request.POST if request.POST.get("action") in ("add_off", "remove_off") else None, language=language)
    if request.method == "POST":
        action = request.POST.get("action")
        form = hours if action == "hours" else off_form
        if action not in ("hours", "add_off", "remove_off"):
            raise PermissionDenied
        if form.is_valid():
            try:
                if action == "hours":
                    replace_hours(barber.pk, form.cleaned_data["shifts"])
                elif action == "add_off":
                    add_days_off(barber.pk, form.cleaned_data["date"], form.cleaned_data["end_date"])
                else:
                    change_day_off(barber.pk, form.cleaned_data["date"], remove=True)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "Schedule saved. / Графикът е запазен.")
                return redirect("booking:hours", pk=barber.pk)
    return page(request, "hours", {"barber": barber, "hours": hours, "off_form": off_form, "days_off": barber.days_off.all()})


@never_cache
@staff_required
@require_POST
def staff_cancel(request, pk):
    appointment = get_object_or_404(Appointment.objects.select_related("barber"), pk=pk)
    require_edit(request, appointment.barber)
    cancel_appointment(appointment)
    messages.success(request, "Appointment cancelled. / Резервацията е отменена.")
    return redirect("booking:schedule")


@never_cache
@staff_required
def services(request):
    require_owner(request)
    return page(request, "services", {"services": Service.objects.all()})


@never_cache
@staff_required
@require_http_methods(["GET", "POST"])
def service_edit(request, pk=None):
    require_owner(request)
    language = language_for(request)
    service = get_object_or_404(Service, pk=pk) if pk else None
    form = ServiceForm(request.POST or None, instance=service, language=language)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Service saved. / Услугата е запазена.")
        return redirect("booking:services")
    return page(request, "service_edit", {"form": form})
