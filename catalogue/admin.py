from django.contrib import admin

from .models import Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "duration_minutes", "price", "is_active", "display_order")
    list_filter = ("is_active",)
    search_fields = ("name", "name_bg", "description", "description_bg")
    list_editable = ("is_active", "display_order")
