import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ShopManager(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shop_manager")


class Barber(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="barber")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    services = models.ManyToManyField("catalogue.Service", related_name="barbers", blank=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


class WorkingHours(models.Model):
    barber = models.ForeignKey(Barber, on_delete=models.CASCADE, related_name="working_hours")
    weekday = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(6)])
    opens_at = models.TimeField()
    closes_at = models.TimeField()

    class Meta:
        ordering = ["weekday"]
        constraints = [
            models.UniqueConstraint(fields=["barber", "weekday"], name="one_shift_per_weekday"),
            models.CheckConstraint(condition=models.Q(weekday__lte=6), name="valid_weekday"),
            models.CheckConstraint(condition=models.Q(closes_at__gt=models.F("opens_at")), name="shift_positive"),
        ]


class DayOff(models.Model):
    barber = models.ForeignKey(Barber, on_delete=models.CASCADE, related_name="days_off")
    date = models.DateField()

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["barber", "date"], name="one_day_off")]


class Appointment(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    request_id = models.UUIDField(unique=True, editable=False)
    barber = models.ForeignKey(Barber, on_delete=models.PROTECT, related_name="appointments")
    service = models.ForeignKey("catalogue.Service", on_delete=models.PROTECT)
    service_name = models.CharField(max_length=120)
    service_name_bg = models.CharField(max_length=120, blank=True)
    duration_minutes = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=8, decimal_places=2)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    customer_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=16)
    email = models.EmailField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "pk"]
        indexes = [models.Index(fields=["barber", "starts_at", "ends_at"], name="appointment_slot_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="appointment_positive"),
            models.CheckConstraint(condition=models.Q(duration_minutes__gt=0), name="appointment_duration_positive"),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="appointment_price_nonnegative"),
        ]
