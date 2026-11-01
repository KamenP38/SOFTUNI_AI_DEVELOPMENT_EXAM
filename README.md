# Alan Barberhouse

A single-shop Django site with a bilingual, server-rendered homepage and an editable service catalogue. Bulgarian is the default; the **BG | EN** switch in the top-right corner selects a language and remembers it in the browser session. This first increment covers the homepage only. Booking, barber accounts and schedule management are future work.

## Local setup (Windows PowerShell)

Run these commands from the repository root with Python 3.11 installed. All dependencies stay in this project's virtual environment; activation is unnecessary.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DJANGO_DEBUG = "1"
$env:DJANGO_SECRET_KEY = (& .\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo_services
.\.venv\Scripts\python.exe manage.py runserver
```

Open <http://127.0.0.1:8000/>. Stop the server with Ctrl+C. Environment variables above apply to the current PowerShell session; set them again in a new terminal. A `.env` file is **not** automatically loaded. Keep secrets out of source control.

SQLite (`db.sqlite3`, ignored by Git) is the default for this initial local preview. PostgreSQL is the target database for the booking application, particularly its future concurrency rules. SQLite preview does not verify PostgreSQL behavior.

## Manage services

While the server is running, create a local administrator in another configured terminal:

```powershell
$env:DJANGO_DEBUG = "1"
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Use <http://127.0.0.1:8000/admin/> to create or edit services. Django's built-in admin requires staff access and the appropriate model permissions. No administrator credentials are shipped.

- `name` and `description` are English; `name_bg` and `description_bg` are Bulgarian. Missing Bulgarian fields individually fall back to English. English service names are unique.
- Duration is an **average** in whole minutes and must be greater than zero. Price is a decimal EUR amount and cannot be negative. Both form validators and database constraints enforce these numeric rules.
- Only active services appear on the homepage. They sort by display order, then English name, then primary key. Both languages use the same order and values.
- The six seeded services, their descriptions, times and EUR prices are **mock data chosen for this prototype**, not verified shop offerings. Public listings did not establish an official price list. The homepage labels this clearly in both languages.
- `seed_demo_services` uses `get_or_create` by English name. It creates missing named examples without updating any existing fields, including translated fields or inactive state. Re-running it preserves edits. Renaming a seeded English name makes it a different entry: a later seed run can recreate its original name. Do not use the command as a synchronization tool or on a real catalogue.
- After the actual catalogue is confirmed, replace the examples through admin, then set `SHOW_DEMO_NOTICE=0` to remove the sample notice.

## Configuration

| Environment variable | Default / purpose |
| --- | --- |
| `DJANGO_DEBUG` | `0`; set exactly `1` for local preview and development static files |
| `DJANGO_SECRET_KEY` | Required with debug off; use a persistent secret in deployed environments. Debug mode can generate an ephemeral key if absent, invalidating sessions on restart. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames; localhost/loopback in debug, otherwise empty |
| `SHOP_NAME` | `Alan Barberhouse` in both languages |
| `SHOW_DEMO_NOTICE` | `1`; retain until real services/prices are confirmed |
| `DATABASE_BACKEND` | `sqlite`; set `postgresql` to use PostgreSQL |
| `POSTGRES_DB` | `barber_shop` |
| `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | Empty; set locally for your database role |
| `POSTGRES_HOST` | `localhost` |
| `POSTGRES_PORT` | `5432` |

For a local PostgreSQL database that you have already created:

```powershell
$env:DJANGO_DEBUG = "1"
$env:DATABASE_BACKEND = "postgresql"
$env:POSTGRES_DB = "barber_shop"
$env:POSTGRES_USER = "barber_shop"
$env:POSTGRES_PASSWORD = "your-local-database-password"
$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "5432"
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo_services
.\.venv\Scripts\python.exe manage.py runserver
```

Use an isolated local database and synthetic data for tests. Do not point test commands at a production database. Moving from SQLite to PostgreSQL does not copy existing data.

Debug-off settings require a secret, enable HTTPS redirects and secure session/CSRF cookies. Deployment is not included: configure a production WSGI/ASGI server, HTTPS, allowed hosts and static-file serving before deploying. Review `manage.py check --deploy` against the intended environment. The development server is for local use only.

## Structure and assets

- `config/`: settings and root routes, WSGI/ASGI entry points.
- `catalogue/`: service model, admin, migrations, homepage view and seed command.
- `catalogue/content.py`: small explicit BG/EN UI dictionaries. No translation compilation or JavaScript is needed. `?lang=bg` and `?lang=en` are the only accepted choices; invalid choices retain the previous valid session language or default Bulgarian.
- `catalogue/templates/catalogue/home.html` and `catalogue/static/catalogue/site.css`: semantic homepage and responsive styling, with keyboard focus, a skip link and reduced-motion support.
- `resources/images/`: supplied original photos, exposed as `images/...` through Django's staticfiles mapping. The homepage uses four shop photos; all eight supplied files remain available. No remote fonts, image services or frontend build step are required.

## Checks

```powershell
$env:DJANGO_DEBUG = "1"
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

Dependencies target Python 3.11 and Django 5.2 LTS. The direct dependencies are pinned in `requirements.txt`: [Django 5.2.18 security release](https://www.djangoproject.com/weblog/2026/oct/06/security-releases/) and [Psycopg 3.3.6](https://www.psycopg.org/download/), with the binary PostgreSQL adapter for straightforward Windows setup. Re-check supported security releases when maintaining the project.
