from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import password_validators_help_text_html, validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.formats import date_format

from catalogue.models import Service
from .models import Barber
from .rules import PHONE_ERROR, day_off_dates, normalize_phone, replace_hours

WEEKDAYS = [("Monday", "Понеделник"), ("Tuesday", "Вторник"), ("Wednesday", "Сряда"),
            ("Thursday", "Четвъртък"), ("Friday", "Петък"), ("Saturday", "Събота"), ("Sunday", "Неделя")]


class ServiceChoiceField(forms.ModelChoiceField):
    language = "bg"

    def label_from_instance(self, obj):
        name = (obj.name_bg or obj.name) if self.language == "bg" else obj.name
        return f"{name} · {obj.duration_minutes} min · {obj.price:.2f} EUR"


class AssignedServicesField(forms.ModelMultipleChoiceField):
    language = "bg"

    def label_from_instance(self, obj):
        name = (obj.name_bg or obj.name) if self.language == "bg" else obj.name
        if not obj.is_active:
            name += " (неактивна)" if self.language == "bg" else " (inactive)"
        return name


class AvailabilitySelect(forms.Select):
    """Keep closed dates visible without offering them as new selections."""

    def __init__(self, *args, disabled_values=(), available_values=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.disabled_values = set(disabled_values)
        self.available_values = available_values

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if str(value) in self.disabled_values:
            option["attrs"]["disabled"] = True
        if self.available_values is not None and value:
            option["attrs"]["data-available"] = "true" if str(value) in self.available_values else "false"
        return option


class SelectionForm(forms.Form):
    service = ServiceChoiceField(queryset=Service.objects.filter(is_active=True), required=False)
    barber = forms.ModelChoiceField(queryset=Barber.objects.filter(is_active=True, user__is_active=True), required=False)
    date = forms.DateField(required=False, widget=forms.Select())

    def __init__(self, *args, language="bg", availability=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].language = language
        for key, en, bg in [("service", "Service", "Услуга"), ("barber", "Barber", "Бръснар"), ("date", "Date", "Дата")]:
            self.fields[key].label = bg if language == "bg" else en
        if availability is not None:
            self.configure_availability(availability, language)

    def configure_availability(self, availability, language):
        self.values = {key: str(self.data.get(key, "")) for key in ("service", "barber", "date")}
        choices, self.has_matches = availability.matching_choices(self.values)
        unavailable = "няма свободни часове" if language == "bg" else "unavailable"
        prompt = "Изберете…" if language == "bg" else "Choose…"
        labels = {
            "service": {str(item.pk): self.fields["service"].label_from_instance(item) for item in availability.services},
            "barber": {str(item.pk): item.name for item in availability.barbers},
            "date": {day.isoformat(): date_format(day, "D, d M Y") for day in availability.dates},
        }
        for key, field in self.fields.items():
            current = self.values[key]
            options = [("", prompt)]
            disabled = set()
            for value, label in labels[key].items():
                if value in choices[key]:
                    options.append((value, label))
                elif key == "date" or value == current:
                    options.append((value, f"{label} — {unavailable}"))
                    if value != current:
                        disabled.add(value)
            if current and current not in labels[key]:
                options.append((current, f"{current} — {unavailable}"))
            # A stale selected value remains enabled so Apply preserves it; the
            # server rejects it and provides recovery links instead of replacing it.
            field.widget = AvailabilitySelect(
                choices=options, disabled_values=disabled,
                attrs={"aria-describedby": "filter-help", "data-filter": key},
                available_values=choices[key] if key == "date" else None,
            )
            if key == "date":
                field.widget.attrs.update({
                    "data-min-date": availability.dates[0].isoformat(),
                    "data-max-date": availability.dates[-1].isoformat(),
                })
            if key != "date":
                field.choices = options


class BookingForm(SelectionForm):
    time = forms.TimeField(widget=forms.HiddenInput(), input_formats=["%H:%M"])
    request_id = forms.UUIDField(widget=forms.HiddenInput())
    customer_name = forms.CharField(min_length=2, max_length=100, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    phone = forms.CharField(
        max_length=80,
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
        error_messages={
            "required": PHONE_ERROR,
            "max_length": PHONE_ERROR,
            "null_characters_not_allowed": PHONE_ERROR,
        },
    )
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"autocomplete": "email"}))

    def __init__(self, *args, language="bg", **kwargs):
        super().__init__(*args, language=language, **kwargs)
        for key, en, bg in [("customer_name", "Your name", "Вашето име"), ("phone", "Phone", "Телефон"), ("email", "Email (optional)", "Имейл (незадължително)")]:
            self.fields[key].label = bg if language == "bg" else en
        self.fields["phone"].help_text = (
            "0 или +359, следвани от точно 9 цифри (0–9), без интервали или разделители. "
            "Примери: 0888123456 / +359888123456."
            if language == "bg" else
            "0 or +359 followed by exactly 9 digits (0–9), without spaces or separators. "
            "Examples: 0888123456 / +359888123456."
        )
        for field in ("service", "barber", "date"):
            self.fields[field].required = True
            self.fields[field].widget = forms.HiddenInput()
        service_id = self.data.get("service") if self.is_bound else self.initial.get("service")
        if str(service_id or "").isdigit():
            self.fields["barber"].queryset = self.fields["barber"].queryset.filter(services__pk=service_id)

    def clean_phone(self):
        return normalize_phone(self.cleaned_data["phone"])


class HoursForm(forms.Form):
    def __init__(self, *args, barber=None, language="bg", **kwargs):
        super().__init__(*args, **kwargs)
        existing = {s.weekday: s for s in barber.working_hours.all()} if barber else {}
        for day, names in enumerate(WEEKDAYS):
            label = names[1] if language == "bg" else names[0]
            shift = existing.get(day)
            self.fields[f"open_{day}"] = forms.BooleanField(required=False, label=label, initial=bool(shift) if barber else True)
            self.fields[f"start_{day}"] = forms.TimeField(required=False, label="От" if language == "bg" else "From",
                widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"), initial=shift.opens_at if shift else "10:00")
            self.fields[f"end_{day}"] = forms.TimeField(required=False, label="До" if language == "bg" else "Until",
                widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"), initial=shift.closes_at if shift else "20:00")

    def rows(self):
        return [(self[f"open_{day}"], self[f"start_{day}"], self[f"end_{day}"]) for day in range(7)]

    def clean(self):
        data = super().clean()
        shifts = {}
        for day in range(7):
            if data.get(f"open_{day}"):
                start, end = data.get(f"start_{day}"), data.get(f"end_{day}")
                if not start or not end or start >= end:
                    raise ValidationError("Each working day needs a start before its end. / Всеки работен ден изисква начало преди края.")
                shifts[day] = (start, end)
        data["shifts"] = shifts
        return data


class DayOffForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, language="bg", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].label = "Дата" if language == "bg" else "Date"


class DayOffRangeForm(DayOffForm):
    end_date = forms.DateField(
        required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )

    def __init__(self, *args, language="bg", **kwargs):
        super().__init__(*args, language=language, **kwargs)
        self.fields["date"].widget.format = "%Y-%m-%d"
        self.fields["date"].label = "Начална дата" if language == "bg" else "Start date"
        self.fields["end_date"].label = (
            "Крайна дата (незадължително)" if language == "bg" else "End date (optional)"
        )
        self.fields["end_date"].help_text = (
            "Включва началната и крайната дата, до 366 дни. "
            "За един почивен ден оставете крайната дата празна."
            if language == "bg" else
            "Includes both start and end dates, up to 366 days. "
            "Leave the end date blank for a single day off."
        )

    def clean(self):
        data = super().clean()
        if data.get("date") and "end_date" in data:
            day_off_dates(data["date"], data["end_date"])
        return data


class BarberForm(forms.Form):
    username = forms.CharField(max_length=150)
    name = forms.CharField(min_length=2, max_length=100)
    password = forms.CharField(required=False, widget=forms.PasswordInput(), strip=False)
    password_confirm = forms.CharField(required=False, widget=forms.PasswordInput(), strip=False)
    services = AssignedServicesField(
        queryset=Service.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple(),
        required=False,
    )
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, barber=None, language="bg", **kwargs):
        self.barber = barber
        initial = kwargs.setdefault("initial", {})
        if barber:
            initial.update(username=barber.user.username, name=barber.name, services=barber.services.all(), is_active=barber.is_active)
        else:
            initial.setdefault("services", Service.objects.filter(is_active=True))
        super().__init__(*args, **kwargs)
        self.fields["services"].language = language
        if barber:
            # Preserve existing inactive assignments without offering them to new accounts.
            self.fields["services"].queryset = Service.objects.filter(
                Q(is_active=True) | Q(barbers=barber)
            ).distinct()
        for key, en, bg in [("username", "Username", "Потребителско име"), ("name", "Display name", "Име"),
                ("password", "Password (leave blank to keep)", "Парола (празно запазва текущата)"),
                ("password_confirm", "Confirm password", "Потвърдете паролата"),
                ("services", "Services", "Услуги"), ("is_active", "Active — accepts bookings", "Активен — приема резервации")]:
            self.fields[key].label = bg if language == "bg" else en
        if not barber:
            self.fields["password"].required = True
            self.fields["password"].label = "Парола" if language == "bg" else "Password"
        self.fields["password"].help_text = password_validators_help_text_html()

    def clean_username(self):
        username = self.cleaned_data["username"]
        field = get_user_model()._meta.get_field("username")
        field.run_validators(username)
        users = get_user_model().objects.filter(username=username)
        if self.barber:
            users = users.exclude(pk=self.barber.user_id)
        if users.exists():
            raise ValidationError("Username already exists. / Името вече съществува.")
        return username

    def clean(self):
        data = super().clean()
        if data.get("password"):
            if data["password"] != data.get("password_confirm"):
                self.add_error("password_confirm", "Passwords do not match. / Паролите не съвпадат.")
            user = get_user_model()(username=data.get("username", ""), first_name=data.get("name", ""))
            try:
                validate_password(data["password"], user)
            except ValidationError as error:
                self.add_error("password", error)
        return data

    @transaction.atomic
    def save(self, shifts=None):
        data = self.cleaned_data
        if self.barber:
            barber = Barber.objects.select_for_update().select_related("user").get(pk=self.barber.pk)
            user = barber.user
        else:
            user = get_user_model()()
            barber = Barber(user=user)
        user.username = data["username"]
        user.is_active = data["is_active"]
        # Barber accounts never receive admin access, including after profile edits.
        user.is_staff = user.is_superuser = False
        if data.get("password"):
            user.set_password(data["password"])
        user.save()
        barber.user = user
        barber.name = data["name"]
        barber.is_active = data["is_active"]
        barber.save()
        barber.services.set(data["services"])
        if shifts is not None:
            replace_hours(barber.pk, shifts)
        return barber


class MyServicesForm(forms.Form):
    services = AssignedServicesField(
        queryset=Service.objects.none(),
        widget=forms.CheckboxSelectMultiple(),
        required=False,
    )

    def __init__(self, *args, barber, language="bg", **kwargs):
        self.barber = barber
        kwargs.setdefault("initial", {})["services"] = barber.services.all()
        super().__init__(*args, **kwargs)
        field = self.fields["services"]
        field.language = language
        field.label = "Услуги, които предлагам" if language == "bg" else "Services I offer"
        field.queryset = Service.objects.filter(
            Q(is_active=True) | Q(barbers=barber)
        ).distinct()

    @transaction.atomic
    def save(self):
        barber = Barber.objects.select_for_update().select_related("user").get(pk=self.barber.pk)
        if not barber.is_active or not barber.user.is_active:
            raise PermissionDenied
        # Revalidate current eligibility after acquiring reserve's barber lock:
        # an inactive assignment removed in another request cannot be added back.
        services = self.fields["services"].clean(
            [service.pk for service in self.cleaned_data["services"]]
        )
        barber.services.set(services)
        return barber


class ServiceForm(forms.ModelForm):
    def __init__(self, *args, language="bg", **kwargs):
        super().__init__(*args, **kwargs)
        for key, field in self.fields.items():
            labels = self.Meta.labels[key].split(" / ")
            field.label = labels[1] if language == "bg" else labels[0]
        self.fields["duration_minutes"].help_text = "Продължителност на резервацията в минути." if language == "bg" else "Appointment duration in minutes."
        self.fields["price"].help_text = "Цена в EUR." if language == "bg" else "Price in EUR."

    class Meta:
        model = Service
        fields = ["name", "name_bg", "description", "description_bg", "duration_minutes", "price", "is_active", "display_order"]
        labels = {"name": "English name / Име на английски", "name_bg": "Bulgarian name / Име на български",
                  "description": "English description / Описание на английски", "description_bg": "Bulgarian description / Описание на български",
                  "duration_minutes": "Minutes / Минути", "price": "Price EUR / Цена EUR", "is_active": "Active / Активна", "display_order": "Order / Подредба"}
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "description_bg": forms.Textarea(attrs={"rows": 3})}
