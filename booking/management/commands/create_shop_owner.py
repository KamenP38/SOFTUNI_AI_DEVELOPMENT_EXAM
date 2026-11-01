from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from booking.models import ShopManager


class Command(BaseCommand):
    help = "Interactively create a shop owner for /staff/ without Django admin privileges."

    def handle(self, *args, **options):
        try:
            username = input("Owner username: ").strip()
            password = getpass("Password: ")
            confirmation = getpass("Confirm password: ")
        except (EOFError, KeyboardInterrupt) as error:
            raise CommandError("Owner creation cancelled.") from error
        if password != confirmation:
            raise CommandError("Passwords do not match.")
        user = get_user_model()(username=username, is_active=True, is_staff=False, is_superuser=False)
        try:
            user.full_clean(exclude=["password"])
            validate_password(password, user)
            with transaction.atomic():
                user.set_password(password)
                user.save()
                ShopManager.objects.create(user=user)
        except (ValidationError, IntegrityError) as error:
            raise CommandError("; ".join(error.messages) if isinstance(error, ValidationError) else "Username already exists.") from error
        self.stdout.write(self.style.SUCCESS(f"Owner '{username}' created. Sign in at /staff/login/."))
