from django.conf import settings
from django.shortcuts import render

from .models import Service
from .content import COPY


def home(request):
    language = request.GET.get("lang")
    if language in COPY:
        request.session["language"] = language
    else:
        language = request.session.get("language", "bg")
    if language not in COPY:
        language = "bg"

    services = [
        {
            "name": (service.name_bg or service.name) if language == "bg" else service.name,
            "description": (
                (service.description_bg or service.description)
                if language == "bg"
                else service.description
            ),
            "duration_minutes": service.duration_minutes,
            "price": service.price,
        }
        for service in Service.objects.filter(is_active=True)
    ]
    return render(
        request,
        "catalogue/home.html",
        {
            "services": services,
            "language": language,
            "copy": COPY[language],
            "shop_name": settings.SHOP_NAME,
            "show_demo_notice": settings.SHOW_DEMO_NOTICE,
        },
    )
