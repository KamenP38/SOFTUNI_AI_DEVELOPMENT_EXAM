"""Deployment-configuration regression tests for config/settings.py.

config/settings.py is imported once per process by Django's settings
machinery, so it cannot be safely re-imported with different environment
variables inside the same test process (Django forbids reconfiguring
settings after setup). Each case below runs a short subprocess with a
controlled environment, following the isolated-subprocess pattern already
used by cypress_audit/fixtures.py, and inspects only the resulting
attributes/exit status. No application database is touched.
"""
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


def run_settings_module(env_overrides, probe=""):
    """Import config.settings in a fresh subprocess with a minimal, explicit env.

    `probe` is appended Python source that may inspect the already-imported
    `config.settings` module as `s`; its stdout is returned for assertions.
    """
    import os

    env = os.environ.copy()
    for key in ("DJANGO_DEBUG", "DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS", "DATABASE_BACKEND"):
        env.pop(key, None)
    env.update(env_overrides)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings"
    # django.setup() makes django.conf.settings usable for probes that read
    # settings indirectly (e.g. the cache backend registry).
    script = "import django; django.setup(); import config.settings as s\n" + probe
    return subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=30,
    )


class ProductionSettingsFailSafeTests(SimpleTestCase):
    """A misconfigured production deployment must fail to start, not run insecurely."""

    def test_debug_off_without_secret_key_refuses_to_start(self):
        result = run_settings_module({"DJANGO_DEBUG": "0", "DATABASE_BACKEND": "sqlite"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_debug_off_without_allowed_hosts_defaults_to_empty_not_permissive(self):
        result = run_settings_module(
            {"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "test-only-not-real", "DATABASE_BACKEND": "sqlite"},
            probe="print(s.ALLOWED_HOSTS)",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Django rejects every Host header rather than silently accepting any host.
        self.assertEqual(result.stdout.strip(), "[]")

    def test_debug_off_forces_secure_cookies_and_ssl_redirect(self):
        result = run_settings_module(
            {"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "test-only-not-real", "DATABASE_BACKEND": "sqlite"},
            probe="print(s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT)",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True True True")

    def test_unknown_database_backend_refuses_to_start(self):
        result = run_settings_module({
            "DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "test-only-not-real", "DATABASE_BACKEND": "mysql",
        })
        self.assertEqual(result.returncode, 1)
        self.assertIn("DATABASE_BACKEND must be sqlite or postgresql", result.stderr)

    def test_debug_mode_allows_localhost_without_explicit_hosts(self):
        # Convenience default for local development only; DEBUG defaults to
        # off (see test_debug_off_without_secret_key_refuses_to_start), so a
        # deployment must opt in to DEBUG before this permissive list applies.
        result = run_settings_module(
            {"DJANGO_DEBUG": "1", "DATABASE_BACKEND": "sqlite"},
            probe="print(s.ALLOWED_HOSTS)",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "['localhost', '127.0.0.1', '[::1]']")

    def test_default_cache_backend_is_process_local(self):
        """Document a real limitation: config/settings.py defines no CACHES.

        booking.views.throttled() rate-limits login and booking submissions
        using the default cache (django.core.cache.cache). Without an explicit
        CACHES setting, Django uses LocMemCache, which keeps state only in the
        current process. Behind more than one worker process, each worker
        enforces the limit independently, so the effective rate limit is
        multiplied by the worker count. This test pins the current behavior so
        a future change to CACHES is a deliberate, reviewed decision rather
        than a silent regression; it does not assert this is sufficient for
        a multi-worker deployment (see docs/independent-audit.md).
        """
        result = run_settings_module(
            {"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "test-only-not-real", "DATABASE_BACKEND": "sqlite"},
            probe=(
                "from django.core.cache import caches\n"
                "print(type(caches['default']).__name__)\n"
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "LocMemCache")
