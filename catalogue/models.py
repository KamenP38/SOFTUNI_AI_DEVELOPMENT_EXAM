from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Service(models.Model):
    name = models.CharField(max_length=120, unique=True)
    name_bg = models.CharField("Bulgarian name", max_length=120, blank=True)
    description = models.TextField(blank=True)
    description_bg = models.TextField("Bulgarian description", blank=True)
    duration_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Average appointment duration in minutes.",
    )
    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Price in EUR.",
    )
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0),
                name="service_duration_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0), name="service_price_nonnegative"
            ),
        ]

    def __str__(self):
        return self.name
