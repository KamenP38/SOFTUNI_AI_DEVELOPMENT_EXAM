# Alan Barberhouse

A single-shop Django site with a bilingual, server-rendered homepage, online appointments and custom owner/barber dashboards. Bulgarian is the default; the **BG | EN** switch selects a language and remembers it in the browser session. Owners manage the team, services and schedules through the branded dashboard without using Django admin.

The homepage follows the supplied dark, cream and gold design: a split photo hero, service cards, six gallery photos, testimonials and a contact section. Its appointment links open `/book/`; the phone link remains available. The supplied address and three review excerpts are static reference content, not a live Google feed or newly verified claims. Individual barber availability comes from their saved schedules. Update both language dictionaries when shop details change.

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

SQLite (`db.sqlite3`, ignored by Git) remains the default for local preview and functional tests. PostgreSQL is required for the documented concurrent-booking guarantee. SQLite does not implement row locks or the PostgreSQL exclusion constraint; a successful SQLite test run is not evidence of production concurrency safety.

## Owner setup and everyday use

After migrations, create the first shop owner interactively in a configured terminal:

```powershell
$env:DJANGO_DEBUG = "1"
.\.venv\Scripts\python.exe manage.py create_shop_owner
```

The command prompts for a unique username and a confirmed password, applies Django password validation and hashing, and creates an ordinary active user with a `ShopManager` profile. It does not grant staff or superuser privileges. No credentials are shipped. Sign in at <http://127.0.0.1:8000/staff/login/>.

From the dashboard, choose **Add barber**, set a username, confirmed password, display name and assigned services (active services start selected), then review the initial weekly hours (all days start selected at 10:00–20:00). Account, service assignments and initial hours save together. Barber accounts remain ordinary users without admin access. Use **Edit profile** for services, activation or a password reset; a blank password preserves it. Deactivation stops login/new bookings but retains appointments for the owner to manage. Existing inactive service assignments remain visible and editable; they never allow new bookings while inactive. The owner can also create/edit services in **Manage services**. Existing appointment snapshots do not change with catalogue edits.

Use **Barbers schedules** (**График на бръснарите**) on the dashboard to open the schedule. The separate **Hours & days off** (**Работно време и почивки**) action on team cards opens weekly hours and days-off editing for owners and the assigned barber. Owners can view and edit all schedules. Active barbers can edit their own weekly hours and days off, and view colleagues' working hours and anonymous booked blocks. A colleague never receives customer names, phone numbers, email addresses, booking references or cancellation controls. Owner/assigned-barber views show appointment details and cancellation buttons. Day and rolling seven-day views support a barber filter. Django admin remains an optional developer tool; everyday shop workflows do not require it.

Active barbers can choose **My services** on their dashboard to update only their own service assignments. They can add active catalogue services, retain or remove already assigned inactive services, or clear every selection. With no active service selected, clients cannot make new bookings with that barber; the barber can return to add active services again. An inactive service removed from the selection cannot be added back until the owner activates it. Saving immediately updates public booking filters and reservation eligibility, while existing appointments retain their service, time, duration and price snapshots. Barbers cannot change the catalogue, prices, durations, accounts or colleagues' assignments through this form. The owner retains assignment editing through **Edit profile**.

## Manage services

- `name` and `description` are English; `name_bg` and `description_bg` are Bulgarian. Missing Bulgarian fields individually fall back to English. English service names are unique.
- Duration is an **average** in whole minutes and must be greater than zero. Price is a decimal EUR amount and cannot be negative. Both form validators and database constraints enforce these numeric rules.
- Only active services appear on the homepage. They sort by display order, then English name, then primary key. Both languages use the same order and values.
- The six seeded services, their descriptions, times and EUR prices are **mock data chosen for this prototype**, not verified shop offerings. Public listings did not establish an official price list. The homepage labels this clearly in both languages.
- `seed_demo_services` uses `get_or_create` by English name. It creates missing named examples without updating any existing fields, including translated fields or inactive state. Re-running it preserves edits. Renaming a seeded English name makes it a different entry: a later seed run can recreate its original name. Do not use the command as a synchronization tool or on a real catalogue.
- Migration `0003_refresh_unchanged_demo_services` replaces the original six mock entries with the approved reference menu only when every original field is unchanged, including Bulgarian text, order and active state. It skips rows whose target English name already exists and does not add rows to an empty database. Its reverse operation likewise matches every new field and skips name collisions. Edited catalogue entries remain untouched; a reverse migration cannot distinguish an independently created row that exactly matches a new example.
- After the actual catalogue is confirmed, replace the examples through **Manage services**, then set `SHOW_DEMO_NOTICE=0` to remove the sample notice.

The current illustrative menu is:

| Service | Average duration | Price |
| --- | --- | --- |
| Classic Haircut | 30 min | 20.00 EUR |
| Beard Trim & Shape | 30 min | 15.00 EUR |
| Fade & Taper | 45 min | 25.00 EUR |
| Hot Towel Shave | 30 min | 25.00 EUR |
| Cut & Beard Combo | 60 min | 35.00 EUR |
| Kids Cut | 30 min | 15.00 EUR |

## Booking and schedule rules

- `/book/` lets a customer choose an active service, eligible active barber (with an active user account), date and available start. Service duration/price are shown before confirmation. The customer supplies a 2–100 character name, mandatory phone and optional email. The form and direct reservation share server-side phone validation: `0` or `+359` followed by exactly nine ASCII digits (0–9), for example `0888123456` or `+359888123456`. Surrounding whitespace is trimmed; internal whitespace, separators, letters, Unicode digits and other prefixes are rejected. No operator-prefix restriction is applied. Email is validated if supplied. No account, payment, email or SMS delivery is involved.
- Service, barber and date can be selected in any order, with no automatic selections (including today). Each field offers alternatives that have at least one bookable slot matching the other two selections; when no date is selected, the whole 29-date window is considered. Duration, assignments, active accounts, shifts, days off and existing bookings all affect these options. Unavailable dates stay visible and disabled. A stale or incompatible selection stays visible with an unavailable label and recovery message; **Clear** removes one filter and **Reset filters** removes all three. Times appear only after all three choices, and contact details after choosing a time. Changing filters clears the selected time. JavaScript refreshes on any filter change; **Apply filters**, clear/reset links and time links also work without JavaScript and preserve the language.
- With JavaScript, the date dropdown becomes a compact BG/EN calendar. Selecting a date still narrows services and barbers. Unavailable days are greyed out and cannot be chosen; they remain keyboard-focusable so their full date and unavailable status can be read. Month navigation is bounded to the server's booking window, with no automatic date selection. Arrow keys move by day/week, Home/End move within the week, Page Up/Down change month, and Enter/Space choose an available day. The selected date has a gold highlight and a text summary; a stale selection remains visible with its warning. **Clear** and **Reset filters** also reset the calendar. Without JavaScript the original server-rendered date dropdown and **Apply filters** remain functional.
- With JavaScript, filter changes, **Apply filters**, **Clear**, **Reset filters** and time selection fetch the same Django GET page and replace only its booking content, without a full-page navigation. Successful updates enter browser history and keep language links current; Back/Forward refreshes the corresponding selection. Completing all three filters advances focus and scroll to the time heading when available times return; choosing a time advances to the details heading, followed by the appointment summary and required customer fields. This uses smooth scrolling unless reduced motion is preferred. Moving focus elsewhere while waiting cancels that automatic advance. Partial selections, clear/reset, failed updates, no-slot results and Back/Forward retain focus and scroll where possible; no-slot results keep the recovery warning beside the filters. Browsing months survives filter changes (clearing the date or resetting filters resets the month). Old times and the confirmation form disappear immediately while refreshing. A failed refresh keeps them unavailable and offers **Try again** without a reload. Name, phone and email drafts remain only in page memory while choosing another time; they are never added to GET URLs or browser storage. GETs run one at a time and coalesce rapid changes so older responses cannot replace newer choices or race session-issued confirmation tokens. Final confirmation remains a normal CSRF-protected POST.
- Public filtering builds a fresh, request-local availability snapshot using at most six inventory queries, fetching only anonymous appointment intervals. Its slot calculation is shared with transactional reservation checks; it never substitutes for those checks and is never cached across requests. A failed or stale booking submission refreshes availability and displays errors; session-authorized retries still return the original appointment before mutable catalogue validation.
- Dates run from today through today + 28 days inclusive, in `Europe/Sofia`. Starts must be strictly future and on a quarter-hour wall-clock boundary, rounded up from opening. The full service duration must fit one continuous weekly shift; an absent shift or dated day off closes the day. Adjacent bookings are allowed, with no buffers or gap avoidance. Different barbers have independent calendars. Nonexistent/ambiguous daylight-saving starts are omitted.
- `booking.rules.reserve` starts a transaction, locks the barber row, re-fetches the service, rechecks eligibility and availability, then stores immutable service-name/duration/price snapshots. Booking, schedule and service-assignment mutations use the same barber lock. **My services** rechecks account activity and allowed assignments under that lock, then updates only the service relationship. PostgreSQL migration `booking.0002` enables `btree_gist` and adds the `booking_no_overlap` GiST exclusion on barber and `[starts_at, ends_at)` for noncancelled rows. PostgreSQL enforces this even if a write bypasses the application. The migration is deliberately a no-op on SQLite. A PostgreSQL role running migrations must be allowed to install the trusted extension (or have an administrator install it beforehand).
- Each confirmation form has a session-issued UUID. Its unique database request ID makes retries idempotent; the session retains the most recent 30 issued IDs. Successful bookings add their random references to the most recent 30 authorized session references. Knowing a confirmation URL alone does not grant access. Keep the browser session to view/cancel; deleting cookies, logout or session expiry removes customer access. No recovery-by-phone/reference lookup is exposed.
- Customer cancellation is POST-only, session-authorized and limited to appointments that have not started. Owners can cancel any appointment and active barbers their own, including past appointments. All cancellations retain records and release the occupied time. There is no rescheduling workflow: cancel and rebook.
- Weekly-hours and day-off changes lock the barber and reject the entire update if any noncancelled appointment ending after now would no longer fit. The error lists conflicting dates/times. Schedule changes never silently cancel appointments. Profiles/service assignments can be deactivated without erasing existing bookings.
- **Hours & days off** accepts a start date and optional end date for leave. Both endpoints are included; leaving the end blank adds one day. Ranges may contain at most 366 days and the end cannot precede the start. The entire range is checked under the same barber lock before any dates are saved, so one conflicting ongoing or future appointment rejects all proposed dates and retains the form inputs. Existing days off are retained without duplication. Removal remains one day at a time. `booking.rules.add_days_off(barber_id, start_date, end_date=None)` shares validation and the locked mutation path with the existing single-day `change_day_off` rule; direct calls enforce the same range limits.
- Private/customer pages are never cached. All changes require CSRF-protected POSTs; role and object permissions are checked on the server. Login uses a fixed internal destination. Passwords are excluded from Django error reports. A small cache-based per-IP throttle limits booking attempts to 30 and login attempts to 20 per 15 minutes. It trusts `REMOTE_ADDR`, not client forwarding headers. The default local-memory cache is per process and resets on restart; this is a development safeguard, not a distributed production abuse-control system.

| Route | Purpose |
| --- | --- |
| `/book/` | Public service/barber/date/time selection and confirmation |
| `/book/<reference>/` | Session-authorized appointment details |
| `/book/<reference>/cancel/` | Customer cancellation (POST) |
| `/staff/login/`, `/staff/logout/` | Staff sign-in and POST-only sign-out |
| `/staff/` | Owner/barber dashboard |
| `/staff/my-services/` | Active barber's own service assignments (GET/POST, no target ID) |
| `/staff/schedule/` | Day/seven-day calendar (`date`, `view=day`, `barber` filters) |
| `/staff/barbers/new/`, `/staff/barbers/<id>/` | Owner account creation/profile editing |
| `/staff/barbers/<id>/hours/` | Weekly hours and days off (owner or same barber) |
| `/staff/appointments/<id>/cancel/` | Authorized staff cancellation (POST) |
| `/staff/services/`, `/staff/services/new/`, `/staff/services/<id>/` | Owner catalogue management |

## Environment configuration

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

For PostgreSQL verification, use a disposable development role/database and the same `POSTGRES_*` variables, then run `manage.py test`. Django creates a separate `test_<POSTGRES_DB>` database; the role needs `CREATEDB` and permission to install `btree_gist` there. This validates the vendor-specific migration and any PostgreSQL-only concurrency tests. SQLite runs may intentionally skip PostgreSQL-specific tests. Never use production credentials or a production database for verification.

Debug-off settings require a secret, enable HTTPS redirects and secure session/CSRF cookies. Deployment is not included: configure a production WSGI/ASGI server, HTTPS, allowed hosts and static-file serving before deploying. Review `manage.py check --deploy` against the intended environment. The development server is for local use only.

## Structure and assets

- `config/`: settings and root routes, WSGI/ASGI entry points.
- `catalogue/`: service model, admin, migrations, homepage view and seed command.
- `booking/`: owner/barber profiles, hours, days off, appointment snapshots, forms, permissions, shared transactional rules, views and branded templates. `create_shop_owner` is the interactive owner bootstrap command.
- `booking/static/booking/booking.js`: progressively enhances all three booking filters with automatic refresh and the date calendar. The date select's explicit availability metadata and window bounds are the calendar's sole source of availability; JavaScript contains no booking rules. **Apply filters** and the date dropdown work without JavaScript; server validation remains authoritative.
- `catalogue/content.py`: small explicit BG/EN UI dictionaries. No translation compilation or JavaScript is needed. `?lang=bg` and `?lang=en` are the only accepted choices; invalid choices retain the previous valid session language or default Bulgarian.
- `catalogue/templates/catalogue/home.html` and `catalogue/static/catalogue/site.css`: semantic homepage and responsive styling, with keyboard focus, a skip link and reduced-motion support.
- `resources/images/`: supplied original photos, exposed as `images/...` through Django's staticfiles mapping. The homepage uses `interior-dark.jpg` in the hero and six gallery photos; all eight supplied files remain available.
- Playfair Display and Barlow are requested from Google Fonts with `display=swap`. Georgia and Arial/sans-serif fallbacks keep the page usable when external fonts are unavailable. Photos are served locally; no frontend build step or JavaScript is required. The gold service strip is static, and reduced-motion preferences disable smooth scrolling and hover transitions.

## Checks

```powershell
$env:DJANGO_DEBUG = "1"
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

Run `node booking/test_inline_booking.cjs` for dependency-free request-controller unit checks covering queued refreshes, stale responses, customer drafts and retries; these are not browser or calendar visual tests.

### Cypress UI audit

The repository-local `test-agent` follows `.agents/skills/cypress-author/SKILL.md` for browser test authoring. The skill and its references are installed only in this project. Existing Django tests remain responsible for backend rules and database-specific concurrency checks.

```powershell
$env:CYPRESS_CACHE_FOLDER = Join-Path (Get-Location) '.artifacts/cypress-cache'
$env:npm_config_cache = Join-Path (Get-Location) '.artifacts/npm-cache'
npm ci
npm run test:e2e
```

The runner starts and stops its own loopback Django server on port 8766 using `cypress_audit.settings`. It refuses an occupied port and verifies the test server identity. Fixtures reset only `.artifacts/cypress-audit.sqlite3`; never use these fixtures with shop/customer data. The audit freezes Django's clock at 15 November 2026 so month navigation and future bookings are repeatable. Tests use synthetic accounts, compare business data before/after actions, and leave screenshots and results under `.artifacts/cypress/`. Node dependencies and downloaded browser binaries are ignored by Git. This test setup is not a production deployment configuration.

See [the UI audit report](docs/ui-audit.md) for tested actions, findings and coverage limits. To run one spec, pass its path, for example `npm run test:e2e -- cypress/e2e/staff.cy.js`.

The audit currently retains failing checks for findings that need review; a nonzero result should be investigated using the report, not suppressed by skipping those tests.

Dependencies target Python 3.11 and Django 5.2 LTS. The direct dependencies are pinned in `requirements.txt`: [Django 5.2.18 security release](https://www.djangoproject.com/weblog/2026/oct/06/security-releases/) and [Psycopg 3.3.6](https://www.psycopg.org/download/), with the binary PostgreSQL adapter for straightforward Windows setup. Re-check supported security releases when maintaining the project.
