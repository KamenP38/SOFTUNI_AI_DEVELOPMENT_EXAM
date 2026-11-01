from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import Barber, ShopManager


def is_owner(user):
    return (
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or ShopManager.objects.filter(user=user).exists())
    )


def active_barber(user):
    if not user.is_authenticated or not user.is_active:
        return None
    return Barber.objects.filter(user=user, is_active=True).first()


def staff_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), "booking:login")
        request.is_owner = is_owner(request.user)
        request.barber = active_barber(request.user)
        if not request.is_owner and not request.barber:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def require_owner(request):
    if not request.is_owner:
        raise PermissionDenied


def require_edit(request, barber):
    if not request.is_owner and (not request.barber or request.barber.pk != barber.pk):
        raise PermissionDenied
