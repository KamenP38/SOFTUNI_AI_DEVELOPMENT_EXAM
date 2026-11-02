# Local Cypress UI audit — 2 November 2026

The audit uses real Cypress browser execution and synthetic data. It covers a finite action and boundary matrix; it is **not a claim that every possible input, ordering, browser, or race has been exhausted**. Existing application edits were preserved. No product fixes were made during this audit.

## Execution and isolation

- Cypress **16.2.1**, headless **Electron 146**, Node **24.12.0**, Windows 11; Django from the repository's `.venv`.
- Desktop **1440 × 1000** and mobile **390 × 844** CSS viewports. The Electron outer window is 1920 × 1200 so screenshots are not cropped; background animation throttling is disabled for reliable guided-scroll observation. This is mobile viewport emulation, not a physical mobile browser.
- Database: SQLite at **`.artifacts/cypress-audit.sqlite3`**, fixed by `cypress_audit.settings`. The fixture helper checks the resolved database path and settings module before every command. It never targets `db.sqlite3` or a PostgreSQL server.
- All users, contact details and appointments are synthetic. Mail uses Django's in-memory backend. The database is flushed and reseeded **before each test**; tests are independent.
- The Django clock is fixed only in audit settings at **2026-11-15 10:00 UTC / 12:00 Sofia**. This makes future bookings and both calendar month buttons deterministic. Cache expiry still uses real elapsed time. A repository-local file cache preserves real throttling behavior and is cleared between tests.
- The server binds only `127.0.0.1:8766`. The runner refuses an occupied port and verifies an audit-only response header before opening Cypress. It pins Cypress's URL, and configuration rejects any effective URL other than that exact loopback address. Both occupied-port and external-URL guards were independently checked: they refused execution before fixture tasks or UI access. No test endpoints were added to the product.
- npm cache and Cypress binary are repository-local: `.artifacts/npm-cache`, `.artifacts/cypress-cache`. The runner clears inherited `ELECTRON_RUN_AS_NODE`, which otherwise prevents Cypress from starting in this editor environment.
- Business snapshots include appointments, services, barbers, service assignments, weekly hours, days off, shop-manager roles, and user identity/profile/password/permission fields. Sessions and `last_login` are deliberately excluded from business equality assertions. Successful hours saves replace rows, so their semantic values are compared where appropriate.

## Commands and results

```powershell
$env:CYPRESS_CACHE_FOLDER = Join-Path (Get-Location) '.artifacts/cypress-cache'
npm.cmd install --save-dev cypress --cache .artifacts/npm-cache --offline=false
npm.cmd run test:e2e
# Optional focused run; the runner still creates its own isolated server:
npm.cmd run test:e2e -- cypress/e2e/public-booking.cy.js
.venv/Scripts/python.exe manage.py check --settings=cypress_audit.settings
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run --settings=cypress_audit.settings
```

Installation succeeded: 171 packages, npm audit reported zero vulnerabilities at installation. Cypress required permission to spawn the browser outside the execution sandbox; it was actually executed, not replaced with HTML-only assertions. Isolated Django system checks passed and migration drift check reported no changes.

**Final complete browser run: 72 tests, 69 passed, 3 failed, 0 pending, 0 skipped; 6 minutes 12 seconds.** These are results from one complete run, not an aggregate. The process exited 1. The failures are two review recommendations in `findings.cy.js` and the unresolved calendar Enter activation check described below. The staff UX observations assert the observed behavior and pass while still reporting it for review.

| Spec | Passed | Failed |
| --- | ---: | ---: |
| `public-booking.cy.js` | 41 | 0 |
| `public-edges.cy.js` | 3 | 1 |
| `staff.cy.js` | 25 | 0 |
| `findings.cy.js` | 0 | 2 |

One bounded follow-up of `public-edges.cy.js` added focus/event diagnostics: **3 passed, 1 failed**, with the same Enter failure. This diagnostic run is reported separately and does not replace the full-run counts. The reusable `npm run cypress:install` command was also exercised successfully against the already installed local binary. JavaScript syntax checks passed for configuration, support, specs and runner/install scripts.

Initial harness validation exposed and corrected test assumptions: hidden mobile navigation CTA selection, immediate sampling during smooth scrolling, a chained attribute assertion losing its DOM subject, service duration's server-side rather than native minimum, and Cypress's default limit on 21 repeated login-page submissions. No application requirement was relaxed to address these. Initial stitched full-page screenshots were not accepted as visual evidence; later viewport screenshots replace them.

## Action and database coverage

`EN/BG × desktop/mobile` below means all four combinations. The two staff roles add eight navigation combinations. Staff mutation boundaries are primarily EN desktop, **not** the complete language/viewport Cartesian product.

| Area / actions | Variants exercised | Expected database result asserted |
| --- | --- | --- |
| Home: skip, logo, section links, hero services, every visible booking CTA, footer staff link, BG/EN | EN/BG × desktop/mobile | No business changes; correct path/hash/language |
| Telephone and map links | Home destination and authorized staff phone href | Correct destinations only; external navigation and OS dialing deliberately not invoked |
| Booking service/barber/date filters | All **six selection orders × four language/viewport combinations** | No business changes; compatible choices and times |
| Apply, each Clear, Reset | Each order above | Preserved/cleared selections as appropriate; no writes |
| Availability rules | Active/inactive services and barbers; beard/Alan-only compatibility; Boris day off; stale unknown service; stale selected unavailable date | No unwanted appointments; recovery available |
| Calendar | Previous/next active buttons and disabled boundaries; arrows, Home/End, Page Up/Down; unavailable date click; Enter attempted but failed | Passing navigation checks leave business data unchanged; Enter completion and its final DB equality assertion did not run |
| Time and confirm | All four language/viewports; both phone prefixes; other compatible barber/service pairs; 15/30-minute services; final fitting slot; email present/absent; two-character name; trimmed phone | Exactly the intended appointments, correct assigned barber/service and stored duration/price/contact fields |
| Guided booking steps | All four language/viewports | Focus and settled heading geometry checked; no scroll-dependent database changes |
| Invalid details | Missing phone; too short/long phone; spaces, foreign prefix, letters, Unicode digits; short name; malformed email | Visible server errors and exact unchanged business snapshot |
| Phone help/error | EN validation flow | Explicit prefix, nine-digit rule and both examples visible |
| Failed/rapid availability requests | Controlled 503, Retry, delayed/coalesced filter changes, Back/Forward | Old times/forms cleared, draft restored, latest intent preserved; no writes |
| Plain form fallback | EN/BG with application enhancement script withheld | Native selection form and time-link flow works; no writes before confirmation |
| Replay/security/stale availability | Replayed issued token; fabricated token; missing CSRF; foreign confirmation reference; another synthetic client takes displayed time | One booking only, 403/404 where applicable, rejected stale submission leaves exact database unchanged |
| Booking date/time boundaries | Today after fixed noon; yesterday; day 29; closing time and unavailable selected time | No past/out-of-window/non-fitting slot accepted |
| Customer cancellation / book again | EN/BG × desktop/mobile | Exactly one cancellation timestamp, retained record and immutable appointment details; other business rows unchanged |
| Staff dashboard and shared navigation | Owner/barber × EN/BG × desktop/mobile; Book, Dashboard, language toggles, schedules, hours, add/edit profile, services, own services, back, logout | Exact business equality; role-appropriate controls |
| Staff schedule | All/day/week, barber filter, date, Show, Previous/Next, edit hours | No writes; selection persistence and correct schedule |
| Staff privacy/permissions | Owner, assigned barber, colleague, inactive barber, unassigned user; forged owner/colleague GET/POST routes | Authorized details only; no colleague phone/email/name disclosure; 403 and no mutation on forbidden actions |
| Staff login/logout | Missing/wrong credentials, unassigned user, inactive barber, owner/barber success, 21 failed submissions | Correct session/navigation, rate limit 429 after threshold, no business changes |
| Staff cancellation | Owner and assigned barber; repeat cancellation | One timestamp change only, record retained, repeat idempotent |
| Weekly hours | Seven day toggles and start/end inputs; invalid/reversed/conflicting shifts; valid update; all days closed | Atomic rejection or intended target barber hours only; appointments unchanged |
| Days off | Required date, single day, inclusive range, reversed range, conflicting appointment, repeated range, 367-day limit, remove | Atomic rejection or exact intended day rows; repeated add does not duplicate; removal affects one date |
| Own services | Preserve unchanged selection, clear all, restore active choices, existing inactive assignment | Own relation rows only; booking snapshots and other barbers unchanged |
| Owner service add/edit | Required fields, duration/price bounds, duplicate name, valid create/edit/deactivate, ordering | Intended service change only; existing appointment price/duration/name snapshots unchanged |
| Owner barber create/edit | Password mismatch, duplicate username, initial seven-day form with one disabled day, assignments, valid create, name change, inactive/reactivate, blank password, password reset and old/new login | Atomic failure or intended user/barber/shift/assignment changes; no admin privileges; retained appointments |
| Console/layout | Browser uncaught errors fail normally; application `console.error` captured; overflow assertions and representative viewport screenshots | No database effect |

Hidden mobile header booking CTA and disabled/out-of-window calendar controls are checked as unavailable states rather than forcibly clicked. An in-window day-off button is actually clicked and verified to leave the prior valid selection, URL and database unchanged. Each action listed in the matrix is exercised somewhere in the suite; this does not mean every action is repeated for every role, language, input, and viewport combination.

## Reproduced findings for further review

### 1. A changed catalogue quote is silently used when confirming an already displayed quote

**Priority: medium; business-policy review required.** Open a 30-minute, EUR 20 appointment, enter valid details, change the service to 45 minutes/EUR 35 before submitting, then click Confirm. The UI creates the booking with **45 minutes and EUR 35**, although the customer last saw 30 minutes/EUR 20. This is booking pricing, not a payment charge; the application does not take payment.

The guarded fixture changes only the synthetic service to reproduce a concurrent catalogue edit. The actual Confirm button performs the reservation. The stored row is recorded in `.artifacts/cypress/stale-quote-observation.json`. `booking/rules.py:176` reloads the current service and lines 190–191 snapshot its current duration and price. Recommended review: decide whether to require reconfirmation, preserve a signed quote, or explicitly document a different rule. Reconfirmation is a review recommendation, not an already agreed requirement. The diagnostic test fails on the newly created row so this observation remains visible.

### 2. Switching booking language loses entered customer details

**Priority: low to medium UX.** Reach the details step in EN, type a name and phone, then click BG. The selected service/barber/date/time survive, but the entered name and phone are empty after navigation. The database remains unchanged. The diagnostic expectation that the draft survives fails.

`booking/templates/booking/base.html:36` uses ordinary language links. `booking/static/booking/booking.js:180` keeps drafts only for inline booking refreshes, and `updateLanguageLinks` updates link targets without persisting the draft through a page load. Review whether language changes should preserve the unsent draft, including email, and add the reverse-direction regression when fixed.

### 3. A barber with no working hours is labelled “Accepting bookings”

**Priority: low UX.** Activate the synthetic inactive barber, retain an active service, then close all seven weekdays. The database contains zero shifts, and the public selector correctly excludes this barber, but the staff dashboard still says “Accepting bookings”. `booking/templates/booking/dashboard.html:45` bases the label on active status/service presence rather than actual bookable availability. This is misleading status text, not an authorization or booking-integrity failure.

### 4. Confirmation-only password input reports success without changing the password

**Priority: low UX.** Edit a barber, leave Password blank, fill only Confirm password, and Save. The UI says “Profile saved” while the exact business snapshot, including the password hash, is unchanged. `booking/forms.py:254` validates confirmation only when a new password is present. Review whether orphan confirmation input should be rejected or explicitly ignored with clearer feedback. Blank password by itself correctly preserves the existing password.

### 5. Staff cancellation loses the displayed schedule filters

**Priority: low UX.** Open a future date in Day view with a barber filter, then cancel an appointment. Cancellation correctly changes only that appointment, but the redirect goes to `/staff/schedule/` without the date/view/barber query. The displayed schedule returns to its defaults, so the user must navigate back to the date they were reviewing. This was observed in the browser cancellation flows and matches `booking/views.py`'s `staff_cancel` redirect. Consider preserving a validated return query after the POST.

### 6. Calendar Enter activation remains unresolved in Electron/Cypress

**Priority: accessibility follow-up; browser/tool versus application cause not established.** Focus the available 17 November button with the service and barber selected, then send native Enter using `cy.press`. No availability request occurs and the date remains unselected. A bounded follow-up first clicked the calendar border to establish page focus and asserted the focused date button. `document.hasFocus()` was true; the trace recorded **trusted Enter keydown and keyup on the correct button**, but no resulting click. The test still failed waiting for the first availability request.

Evidence is in `keyboard-before.json`, `keyboard-after.json`, `results-keyboard-diagnostic.json` and `run-keyboard-diagnostic.log`. Mouse date selection and arrow-key focus movement pass. The calendar relies on the button's native Enter activation (`booking/static/booking/booking.js` handles click and navigation keys). Confirm using a real keyboard in an independent Chrome/Firefox session before attributing this to application code or making a cross-browser claim. The failed test remains enabled; no synthetic click was substituted for Enter.

## Artifacts and limits

- Canonical full-run raw results: `.artifacts/cypress/results-full-final.json`; final command output: `.artifacts/cypress/run-final.log`; isolated HTTP log: `.artifacts/cypress/server-full-final.log`. The standard `results.json` and `server.log` were restored to these full-run artifacts after the diagnostic.
- Earlier harness runs: `results-initial.json`, `results-second.json`, `results-third.json`, `run-second.log`, `run-third.log`. These do not represent final acceptance results.
- Exact final-run screenshot paths and dimensions: [screenshot index](../.artifacts/cypress/screenshots-final.md), with machine-readable `.artifacts/cypress/screenshots-final.json`. This index contains only captures from the canonical full run. Initial cropped/stitched captures must not be used to infer product defects.
- Application console observations: `.artifacts/cypress/console.jsonl`. Expected negative-test 403/404/429 responses and an intercepted synthetic 503 are intentional; they are not unexplained server failures.
- Guided-scroll geometry: `.artifacts/cypress/scroll-<language>-<viewport>.json`.

All four guided-flow cases passed focus, full heading visibility and the actual CSS scroll destination check (including clamping at the document end). The final BG desktop time heading was at 144.31 px; BG mobile was at 160.44 px because of end-of-document clamping. The final viewport screenshots show the time choices and then the details inputs, and representative home/staff captures were visually inspected. Overflow assertions passed in the tested viewports. No application `console.error` messages were captured across the audit runs; the canonical server log contains no HTTP 5xx responses. The deliberate 503 recovery test is intercepted by Cypress rather than emitted by Django.

PostgreSQL exclusion constraints and simultaneous transaction races were **not** exercised by this SQLite browser audit. Independent backend validation reported 131 tests: 126 passed and 5 PostgreSQL-only tests skipped; the existing Node booking script suite passed 7 tests. Those skips must be resolved on isolated PostgreSQL before claiming concurrent-booking guarantees are verified. The UI stale-slot and replay tests are useful but are not substitutes for genuine concurrent PostgreSQL submissions.

Not separately exhausted: full mutation language/viewport cross-products, other browsers and actual touch/mobile devices, every possible date/string/password, DST transitions in this fixed-clock browser run, superuser-specific UI, empty-catalogue fixtures, the exact 366-day successful range boundary in the browser, past customer/staff cancellation boundaries in the browser, maximum 30 remembered references, 30-reservation throttling, screen-reader operation, and external map/telephone destination behavior. Existing backend tests cover some of these rules; this report does not silently count that as browser coverage.

Official Cypress references used: [task/database integration](https://docs.cypress.io/api/commands/task), [configuration](https://docs.cypress.io/app/references/configuration), [local binary/cache installation](https://docs.cypress.io/app/references/advanced-installation), [browser launch dimensions](https://docs.cypress.io/api/node-events/browser-launch-api), and [secure environment access](https://docs.cypress.io/api/commands/env).

**Thank you for using Cypress!**
