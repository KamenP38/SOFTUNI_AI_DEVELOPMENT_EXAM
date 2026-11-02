# Independent audit — 2 November 2026

This audit independently re-verifies the Django barbershop website and the checks
recorded in `docs/ui-audit.md` and `docs/exam-evidence/`. It does not assume those
documents are correct; every quantitative claim re-checked here was reproduced by
actually running the referenced commands in this session, not by reading the prior
report. Where something could not be reproduced (PostgreSQL), that is stated
explicitly rather than inferred.

No product code was changed. Two test files were added (`config/tests.py`, new) and
one test was added to the existing `booking/tests.py`. No production configuration,
dependency versions, or the real `db.sqlite3` were touched — verified by SHA‑256
hashing `db.sqlite3` before and after every test run in this session (identical
`E8A84CB1…CF0C7` throughout). All prior audit evidence under `docs/ui-audit.md`,
`docs/exam-evidence/` and `.artifacts/` was left in place.

## 1. Assessment summary

The application (Django 5.2.18, server-rendered templates, plain JS, SQLite for
local/dev and PostgreSQL for production concurrency guarantees) is small,
focused and unusually well tested for its size. Permission checks
(`booking/permissions.py`), the booking transaction/lock design
(`booking/rules.py`), and customer-data redaction for colleague schedules
(`booking/views.py:schedule`, `booking/templates/booking/schedule.html`) are
implemented consistently and are covered by targeted backend and browser tests.
Phone validation, inclusive day-off ranges, DST handling and stale-availability
recovery are all implemented more carefully than the minimum product
requirement demands, and the test suite exercises realistic edge cases (Unicode
digit spoofing, leap-day boundaries, CSRF, forged staff routes, 21 repeated
login attempts, etc.).

The prior audits (`docs/ui-audit.md`, `docs/exam-evidence/`) are honest and
well-scoped: every number I re-ran matched what they reported, and the three
documented browser-reproducible findings reproduced exactly, byte-for-byte,
in this independent run. I found no evidence of fabricated or stale results.
I did find one new, currently-relevant dependency-risk item (§3.1) and one
previously undocumented UX gap now pinned by a new test (§3.2), plus a small
number of genuinely missing deployment-configuration tests, which I added.

## 2. Commands run and verified results

Environment: Windows 11, Python 3.11.9 (`.venv`), Django 5.2.18, Node v24.12.0,
Cypress 16.2.1 / Electron 146 (headless), repository root
`c:\Users\Asus\Documents\AI_DEVELOPMENT\softuni_ai_development_exam`.

### 2.1 Django system checks and migrations

```powershell
$env:DJANGO_DEBUG='1'; .venv\Scripts\python.exe manage.py check
# System check identified no issues (0 silenced).
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
# No changes detected
```

### 2.2 Backend test suite (SQLite, in-memory test database)

```powershell
$env:DJANGO_DEBUG='1'; .venv\Scripts\python.exe manage.py test --verbosity=2
```

Django's test runner used `file:memorydb_default?mode=memory&cache=shared`
(SQLite's default in-memory test database; confirmed from the runner's own
"Creating test database" line) — the real `db.sqlite3` was never opened by
`manage.py test`. First run (before my additions): **131 tests, 126 passed, 5
skipped, 0 failed** — identical to the count in `docs/ui-audit.md`. After adding
7 new tests (§4): **138 tests, 133 passed, 5 skipped, 0 failed**. The 5 skips
are all `PostgreSQLBookingTests` cases, correctly gated by
`@skipUnless(connection.vendor == "postgresql", …)`.

### 2.3 Node unit tests for the client-side booking controller

```powershell
node --test booking/test_inline_booking.cjs
```
**7 tests, 7 passed, 0 failed** — matches the prior report.

### 2.4 Cypress end-to-end suite (isolated SQLite, loopback server)

```powershell
npm.cmd run test:e2e
```
This starts `cypress_audit.settings` against `.artifacts/cypress-audit.sqlite3`
only (guarded by `cypress_audit/fixtures.py:guard()` and the port/identity
checks in `scripts/run-cypress.cjs`), never the real database.

**75 tests total: 72 passed, 3 failed, 0 pending, 0 skipped, 9m46s, Electron 146
headless, 1440×1000 (+ some 390×844 mobile) viewports, English/Bulgarian.**

| Spec | Passed | Failed | Notes |
| --- | ---: | ---: | --- |
| `exam-flows.cy.js` | 3 | 0 | Owner/Barber/Client walkthrough (same as `docs/exam-evidence/`) |
| `findings.cy.js` | 0 | 2 | Both failures are intentional, documented review findings |
| `public-booking.cy.js` | 41 | 0 | |
| `public-edges.cy.js` | 3 | 1 | The documented calendar-Enter failure |
| `staff.cy.js` | 25 | 0 | |

This exactly reproduces the previously reported "72 tests, 69 passed, 3
failed" (`docs/ui-audit.md`) plus the 3 passing `exam-flows.cy.js` tests added
since (`docs/exam-evidence/results.json`), for a combined 75/72/3. The three
failures' stack traces matched the documented root causes exactly (§3 below).

### 2.5 Dependency and config checks

```powershell
npm.cmd audit --json            # 171 packages, 0 vulnerabilities (prod 1, dev 171)
manage.py check --deploy        # with DEBUG=0, a real SECRET_KEY, ALLOWED_HOSTS set
```
`check --deploy` reported exactly **one** warning: `security.W004` — no
`SECURE_HSTS_SECONDS` configured. No other deploy warnings (secret key length,
cookie security, SSL redirect are already correctly handled).

### 2.6 PostgreSQL

A PostgreSQL 17 Windows service (`postgresql-x64-17`) is running locally and
port 5432 is reachable, so PostgreSQL is **not absent** in this environment —
but `pg_hba.conf` requires `scram-sha-256` password authentication for every
connection (local and host), and no credentials for this server instance were
available in this session. I did not attempt to guess or brute-force
credentials. Consequently the 5 `PostgreSQLBookingTests` (overlap exclusion,
simultaneous-booking races, idempotent concurrent retries,
hours-change-vs-booking races) remain **unverified in this session**, exactly
as before. This is a different situation from "PostgreSQL unavailable" and
should be recorded precisely: a future session with valid local credentials
(or a disposable role per `README.md`'s PostgreSQL setup section) could
actually run these checks here.

## 3. Findings

### 3.1 New — Pinned Django release has a superseding security patch (Low/Medium, dependency risk)

`requirements.txt:1` pins `Django==5.2.18`, which `README.md:168` correctly
cites as the Oct 6, 2026 security release
(https://www.djangoproject.com/weblog/2026/oct/06/security-releases/, fixing
CVE‑2026‑77050/84429/87890/87975). However, Django's own release index
(https://docs.djangoproject.com/en/5.2/releases/) now lists **Django 5.2.19**
(dated November 3, 2026, i.e. after this pinned version), whose release notes
state it "fixes four security issues with severity 'low' and one security
issue with severity 'moderate' in 5.2.18"
(https://docs.djangoproject.com/en/5.2/releases/5.2.19/). I could not find a
published blog post with the individual CVE breakdown at the time of this
audit (the project weblog index had not yet listed it), so I cannot
characterize the moderate issue further, and I did not change
`requirements.txt`, per this audit's constraints. This is a confirmed,
actionable item: re-check and apply the Django 5.2.19 patch per the project's
own stated policy (`README.md:168`, "Re-check supported security releases when
maintaining the project") before relying on 5.2.18 in production.
`psycopg` 3.3.6 has no published GitHub security advisories as of this audit.

### 3.2 Reproduced — stale catalogue quote is silently honoured at confirmation (Medium, business-policy review)

`booking/rules.py:176-191`. Reproduced exactly: `findings.cy.js`'s second test
opens a 30‑min/€20 appointment, changes the service to 45‑min/€35 via the
fixture (simulating a concurrent catalogue edit), then clicks the original
Confirm button; the appointment is created at **45 min / €35**, not the
quote the customer last saw. Same conclusion as `docs/ui-audit.md`: this is a
genuine, reproducible design choice (reserve() intentionally rereads current
service price/duration), not a bug — but it needs an explicit product
decision (require reconfirmation vs. accept it vs. document it).

### 3.3 Reproduced — switching booking language discards the in-progress customer draft (Low/Medium UX)

`booking/templates/booking/base.html:36`, `booking/static/booking/booking.js:180`.
Reproduced exactly: entering a name/phone, then clicking the BG language link,
clears both fields even though the service/barber/date/time survive. No
database change occurs (confirmed via `assertNoBusinessChange`).

### 3.4 Reproduced — calendar date activation via a real Enter keypress does not fire in this Electron/Cypress session (Low, accessibility/tooling, cause unconfirmed)

`public-edges.cy.js`'s `cy.press(Cypress.Keyboard.Keys.ENTER)` on a focused,
available calendar `<button>` records a trusted keydown/keyup but no
resulting click or availability request, reproducing the previous diagnostic
exactly (`.artifacts/cypress/results-keyboard-diagnostic.json`, 3 passed/1
failed, unchanged). I did not have a second real browser (Chrome/Firefox)
available in this sandbox to test independently, so — like the prior report —
**I cannot confirm whether this is an Electron/Cypress input-simulation
artifact or a genuine `booking/static/booking/booking.js` defect.** Native
`<button>` elements fire `click` on Enter without any JS needed, and I found
no `keydown` handler in `booking.js` that calls `preventDefault()` for the
`Enter` key (only Arrow/Home/End/PageUp/PageDown are intercepted), which is
circumstantial evidence pointing away from an application bug, but this is
not a substitute for testing in a real keyboard-driven browser session.

### 3.5 Reproduced (as a passing, intentionally-informative assertion) — inactive-hours barber still labelled "Accepting bookings" (Low UX)

`booking/templates/booking/dashboard.html:45`. `staff.cy.js`'s
"Audit finding: a barber with active services and no working hours still
says Accepting bookings" **passed** in this run — i.e., it successfully
confirmed the label is still shown even with zero shifts, matching
`docs/ui-audit.md` finding #3 exactly.

### 3.6 Reproduced (as a passing, intentionally-informative assertion) — confirmation-only password change silently no-ops (Low UX)

`booking/forms.py:254` (`BarberForm.clean`). `staff.cy.js`'s "confirmation-only
password edit reports saved but preserves the existing password" **passed**,
confirming the hash is genuinely unchanged while the UI still reports
"Profile saved." Matches `docs/ui-audit.md` finding #4 exactly.

### 3.7 Confirmed by a new test — cancelling from a filtered schedule view loses the display filters (Low UX)

`booking/views.py:staff_cancel` always `redirect("booking:schedule")` with no
query string, so a `POST` from `/staff/schedule/?date=…&view=day&barber=…`
redirects to the unfiltered default view. `docs/ui-audit.md` finding #5 reported
this from manual browser observation only; neither the Cypress cancellation
test nor any Django test asserted on the *query string* of the redirect
(only the 302 status). I added
`booking/tests.py:StaffTests.test_cancel_redirect_drops_the_displayed_schedule_filters`,
which posts with a filtered `Referer` and asserts the `Location` header is the
bare `/staff/schedule/` path — it passes today, formally pinning the current
(arguably undesirable) behavior so a future redirect change is a deliberate,
reviewed decision rather than an untested regression.

### 3.8 Observation — `manage.py check --deploy` flags missing HSTS (Low, deployment readiness)

With a real `DJANGO_SECRET_KEY`/`DJANGO_ALLOWED_HOSTS` and `DJANGO_DEBUG=0`,
`check --deploy` reports only `security.W004` (`SECURE_HSTS_SECONDS` not set).
Every other deploy check (secret key strength, `SESSION_COOKIE_SECURE`,
`CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`) is already correctly configured
in `config/settings.py:104-108`. This is a one-line, low-risk improvement
suggestion for a future HTTPS deployment, not a defect.

### 3.9 Observation — default cache backend is per-process (Low, already documented, now test-pinned)

`config/settings.py` defines no `CACHES` setting, so Django's default
`LocMemCache` backs `booking.views.throttled()` (login/booking rate
limiting). `README.md:76` already documents this precisely ("a development
safeguard, not a distributed production abuse-control system"), so this is
**not a new discovery** — but it was previously undocumented at the test
level. `config/tests.py:test_default_cache_backend_is_process_local` now pins
it, so a future accidental change (e.g., someone adding a shared cache without
reviewing the throttle code, or vice versa) is a visible, deliberate decision.

### 3.10 Observation — Django admin remains reachable at `/admin/` (Informational)

`config/urls.py` includes `admin.site.urls`, and `catalogue/admin.py`
registers `ServiceAdmin`. Shop owners created via `create_shop_owner` have
`is_staff=False` (verified in `booking/management/commands/create_shop_owner.py`
and exercised by `booking/tests.py:OwnerBootstrapTests`), so they cannot reach
it; only a separately created Django superuser can, and `catalogue/tests.py`
already covers that permission boundary correctly. This is an accepted,
tested design (a second, admin-only path to edit services), not a defect —
flagging it only because the audit scope asked about deployment surface area.

## 4. Tests added

All new tests use only synthetic data, the Django test client/`TestCase`, and
(for `config/tests.py`) short, fully isolated subprocesses that never touch
Django's already-configured settings object or any real database file.

| File | Test | Why it was missing / why it matters |
| --- | --- | --- |
| `config/tests.py` (new) | `test_debug_off_without_secret_key_refuses_to_start` | No test previously exercised `config/settings.py`'s fail-closed behavior at all. A refactor could silently drop the `ImproperlyConfigured` guard and ship a missing-secret production deployment. |
| `config/tests.py` | `test_debug_off_without_allowed_hosts_defaults_to_empty_not_permissive` | Confirms a misconfigured deployment rejects all hosts rather than falling back to something permissive. |
| `config/tests.py` | `test_debug_off_forces_secure_cookies_and_ssl_redirect` | Pins `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`/`SECURE_SSL_REDIRECT` together as a single regression target. |
| `config/tests.py` | `test_unknown_database_backend_refuses_to_start` | Pins the `DATABASE_BACKEND` validation guard. |
| `config/tests.py` | `test_debug_mode_allows_localhost_without_explicit_hosts` | Confirms the permissive dev default is genuinely gated behind `DEBUG=1`, not accidentally reachable with debug off. |
| `config/tests.py` | `test_default_cache_backend_is_process_local` | See §3.9 — makes an already-documented limitation testable instead of only prose. |
| `booking/tests.py` | `test_cancel_redirect_drops_the_displayed_schedule_filters` | See §3.7 — the only one of the six `docs/ui-audit.md` findings that had **no** automated test at any level before this audit. |

I deliberately did **not** add new tests that would mostly mirror existing
implementation with little independent value, for example: a staff
dashboard/schedule query-count test (I manually verified, by reading
`booking/views.py:dashboard` and `:schedule`, that both already use
`prefetch_related` for `services`/`working_hours`/`days_off` and a single
grouped `Appointment` query, so there is no N+1 there to catch — only the
public booking filter page currently has a query-count regression test,
`booking/test_filtering.py:test_filter_queries_do_not_grow_per_barber_service_or_date`,
and that remains the right place for it); or a test re-asserting the calendar
Enter-key failure at the Django level (it is a browser/input-simulation
question, not something a Django `TestCase` can observe).

## 5. Coverage evaluation against the requested checklist

Reviewed by reading the relevant code/tests and, where practical, by rerunning
the suites rather than trusting prior claims:

- **Login, account management, role/object permissions**: thoroughly covered
  (`booking/tests.py:StaffTests`, `OwnerBootstrapTests`; `staff.cy.js`).
- **Unauthorized access via direct URLs/modified requests**: covered
  (`test_barber_cannot_manage_accounts_services_or_colleague_schedule`,
  `test_tampered_barber_service_and_outside_dates_rejected`, forged-route
  Cypress checks).
- **Customer contact privacy, session handling, CSRF, escaping, secret
  exposure**: covered; I independently confirmed no `|safe`/`mark_safe`/
  `autoescape off` anywhere in the templates or custom template tags (a
  `grep` across the repository found zero matches), and manually traced
  `schedule.html`'s colleague-privacy branch — it only receives a hand-built
  dict (`starts_at`/`ends_at`) for non-private rows, so there is no way for a
  template change elsewhere to accidentally leak a model attribute.
- **Service/barber filtering, calendar availability, selection orders**:
  extensively covered (`booking/test_filtering.py`, `booking/test_calendar.py`,
  `public-booking.cy.js`).
- **Working hours, inclusive day-off ranges, timezone/date boundaries,
  schedule conflicts**: extensively covered, including DST
  (`booking/rules.py:local_datetime`) and leap-day/366-day boundaries
  (`booking/test_days_off_range.py`).
- **Phone validation (`0`/`+359` + exactly 9 digits)**: covered well beyond the
  stated requirement, including Unicode digit spoofing and operator-prefix
  confusion (`test_phone_requires_bulgarian_prefix_and_nine_ascii_digits`).
- **Booking creation, cancellation, stale availability, duplicate submissions,
  concurrent bookings**: covered on SQLite via session-nonce idempotency and
  stale-slot rejection; **concurrent/overlap guarantees remain unverified
  on PostgreSQL in this session** (§2.6).
- **Service price/duration changes and stored appointment snapshots**:
  covered (`test_snapshot_preserved_when_service_changes`,
  `test_owner_service_management_validates_and_preserves_snapshot`).
- **Expected DB changes / non-changes**: extensively covered via
  `assertNoBusinessChange`/snapshot comparisons across nearly every Cypress
  test.
- **Desktop/mobile, BG/EN, keyboard accessibility, focus/scrolling**: covered
  for the scenarios in `staff.cy.js`/`public-booking.cy.js`; the full
  language×viewport×role cross-product is explicitly not exhausted (as
  already stated in `docs/ui-audit.md`), which I did not attempt to change.
- **Loading/error states, failed requests, rapid input, stale responses**:
  covered (`booking/test_inline_booking.cjs`, `public-edges.cy.js`).
- **Deployment settings, dependency risks, expensive queries**: this is where
  I found the most previously-untested ground — see §3.1, §3.8, §3.9 and the
  new `config/tests.py`.

## 6. Prior findings: confirmed / contradicted / not reproducible

All six numbered findings in `docs/ui-audit.md` were **confirmed**, three of
them via a live failing-test reproduction (stale quote, language-switch draft
loss, calendar Enter) and three via a live passing-but-documenting assertion
(misleading "Accepting bookings" label, confirmation-only password no-op) plus
one previously untested claim now backed by a new test (cancellation redirect
losing filters, §3.7). **None were contradicted.** None were unreproducible —
I was able to exercise all of them in this session using only the existing
tooling. The quantitative claims in `docs/exam-evidence/` (3/3 passing exam
walkthrough, 32+2 screenshots, synthetic data only) were cross-checked against
the actual file counts and `results.json` on disk and are accurate, not
fabricated.

## 7. Prioritized future improvements

Scoped for a small, single-shop Django site — no new frameworks, services, or
architectural changes suggested.

**Functionality**
1. Decide and implement the stale-quote policy (§3.2) — this is a real
   business-policy gap, not just a UX nit.
2. Preserve the in-progress customer draft across a language switch (§3.3).
3. Preserve the schedule's date/view/barber filters through the cancellation
   redirect (§3.7) — now backed by a test to update once fixed.

**Security / privacy**
4. Apply the Django 5.2.19 patch once reviewed (§3.1) — this is time-sensitive
   relative to this audit's date, not a standing recommendation.
5. Consider `SECURE_HSTS_SECONDS` once the production deployment is served
   exclusively over HTTPS (§3.8).

**Reliability**
6. Verify the PostgreSQL overlap-exclusion and concurrency tests on an
   environment with working local PostgreSQL credentials before relying on
   them in production (§2.6) — this remains the single biggest unverified
   guarantee in the whole project.
7. If the site is ever deployed with more than one worker process, replace
   the default `LocMemCache` with a shared backend (e.g. the filesystem cache
   already used safely in `cypress_audit/settings.py`, or a simple shared
   cache) so `booking.views.throttled()` limits are enforced per-shop, not
   per-worker (§3.9). This is already documented as a known limitation; it
   only becomes consequential if/when a multi-worker deployment is chosen.

**Usability / accessibility**
8. Resolve or formally attribute the calendar Enter-key finding (§3.4) using a
   real Chrome/Firefox session, not just Electron.
9. Clarify the "Accepting bookings" label so it reflects actual bookable
   availability, not just active status + any service (§3.5).

**Testing**
10. None of the six `docs/ui-audit.md` findings had been promoted into the
    backend regression suite before this audit except via the Cypress
    `findings.cy.js`/`staff.cy.js` assertions; §3.7's gap is now closed. The
    other five remain intentionally-failing/passing Cypress assertions
    awaiting a product decision — appropriate given they are open questions,
    not yet agreed bugs.
11. Re-attempt the PostgreSQL-specific suite the next time a credentialed
    local or disposable PostgreSQL role is available.

**Maintainability**
12. No maintainability issues found beyond what's already noted in
    `docs/ui-audit.md`; the codebase is small, consistently commented at
    non-obvious points, and the test suite's naming makes intent easy to
    follow.

**Deployment readiness**
13. Track Django 5.2.x security releases against the pinned version as part
    of routine maintenance (the project already does this — `README.md:168`
    — just re-confirm before each deployment, since a newer patch can appear
    between audits, as happened here).
14. Keep `/admin/` restricted to deliberately created superusers only (§3.10);
    no change needed today, just a reminder for future operators.

## 8. Remaining limitations

- **PostgreSQL concurrency/exclusion-constraint guarantees are unverified in
  this session** (§2.6) — a real limitation of this sandbox (no usable
  credentials for the locally running PostgreSQL 17 service), not of the
  product. This must be re-verified with real PostgreSQL access before
  trusting the no-overlap guarantee in production.
- **The calendar Enter-key finding (§3.4) was not isolated to Electron vs.
  application code** — no second real browser was available in this
  environment either.
- I did not perform a line-by-line security audit (static analysis, dependency
  CVE database scan beyond the two checks in §2.5/§3.1, or a penetration test);
  this was a functional/regression/configuration audit, consistent with the
  task's scope.
- I did not re-run the full Bulgarian/mobile/role/viewport cross-product that
  `docs/ui-audit.md` already explicitly declines to claim as exhaustive;
  I instead re-ran the exact same specs that exercise the matrix's
  representative subset and got identical pass/fail results, which is
  evidence the matrix is stable, not evidence it is now exhaustive.
- Screen-reader operation and real touch-device behavior remain untested, as
  before.
