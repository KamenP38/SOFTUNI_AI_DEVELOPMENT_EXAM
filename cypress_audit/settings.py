"""Hard-coded isolated settings: no database or server environment overrides."""
import os
from datetime import datetime, timezone as datetime_timezone

os.environ["DJANGO_DEBUG"] = "1"
os.environ["DJANGO_SECRET_KEY"] = "synthetic-local-cypress-audit-only"
os.environ["DATABASE_BACKEND"] = "sqlite"

from config.settings import *  # noqa: E402,F403

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / ".artifacts" / "cypress-audit.sqlite3",
    "OPTIONS": {"timeout": 20},
}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
    "LOCATION": BASE_DIR / ".artifacts" / "cypress-cache-state",
}}
MIDDLEWARE = ["cypress_audit.middleware.AuditIdentityMiddleware", *MIDDLEWARE]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# A mid-month clock makes both month navigation directions reproducible and
# prevents booking-window boundary tests from depending on the day of execution.
# This module is loaded only by the guarded audit runner and fixture subprocesses.
from django.utils import timezone
timezone.now = lambda: datetime(2026, 11, 15, 10, 0, tzinfo=datetime_timezone.utc)
