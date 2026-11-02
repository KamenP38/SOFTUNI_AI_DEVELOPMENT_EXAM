# Exam walkthrough evidence

All appointment, account and service data shown here is synthetic demonstration data. Names prefixed Demo, test-only phone values and example.invalid email addresses do not identify real customers. The public website's fixed shop branding/contact section remains visible in homepage captures.

The three independent Cypress tests use real browser clicks, typed forms and server responses. Each test starts with freshly seeded data. Owner and barber start on the homepage, click its footer Staff sign in link, and submit credentials in the UI. Client starts with the public service menu. No programmatic login or URL shortcut is used.

**Result: 3 passed, 0 failed, 0 pending, 0 skipped.** Cypress 16.2.1 / Electron 146, English UI, 1200 × 800 desktop viewport, isolated SQLite database on loopback port 8766, application clock frozen at 15 November 2026. The 32 numbered images and 2 compact report images are native browser captures, with real panel/viewport crops and masked passwords.

Run from the repository root:

```powershell
npm run test:e2e -- cypress/e2e/exam-flows.cy.js
.venv\Scripts\python.exe scripts/export-exam-evidence.py
```

## Coverage and database evidence

| Role | UI actions | Database assertions |
| --- | --- | --- |
| Owner | Homepage → login → dashboard → new barber with services/hours → schedule → catalogue price edit → weekly hours → inclusive day-off range | User/barber created, password hashed, 2 service assignments, 6 working days; new price persists while old appointment quotes remain; hours and all 3 days off persist |
| Barber | Homepage → login → dashboard → own services → own hours → inclusive days off → colleague schedule | Only selected service assigned; Monday opening changes; all 3 days off persist; existing appointments retained; colleague customer details and cancel control absent |
| Client | Homepage services → booking → service → barber → calendar date → time → contact details → confirmation | No business writes before confirmation; exactly 1 new appointment with expected barber, service, date/time, contact data, price and duration; other business tables unchanged |

This focused successful-flow suite does not re-test Bulgarian/mobile layouts, invalid inputs, cancellation, other service-selection orders or PostgreSQL concurrent-overlap constraints. These screenshots are not a claim of exhaustive coverage. The earlier audit findings remain in docs/ui-audit.md; this run does not fix or supersede them. No uncaught browser exception or application console.error occurred in the passing run. Initial capture-only failures were corrected: scrolling a short page and choosing a hidden responsive header button. The final workflow uses the visible homepage booking button.

The previous audit results, screenshot index, console log and server log were preserved under .artifacts/cypress/pre-exam before running this spec.

## Numbered walkthrough

| # | Role | Step and evidence | Expected and observed result |
| --- | --- | --- | --- |
| 01 | OWNER | [home staff entry](screenshots/01-owner-home-staff-entry.png) | The public homepage exposes the Staff sign in link. |
| 02 | OWNER | [login form](screenshots/02-owner-login-form.png) | The sign-in form is ready to submit. |
| 03 | OWNER | [dashboard](screenshots/03-owner-dashboard.png) | The correct role dashboard is displayed. |
| 04 | OWNER | [new barber account](screenshots/04-owner-new-barber-account.png) | The new synthetic barber account fields are filled; passwords stay masked. |
| 05 | OWNER | [new barber services hours](screenshots/05-owner-new-barber-services-hours.png) | Initial weekly hours are visible with Sunday closed. |
| 06 | OWNER | [barber created](screenshots/06-owner-barber-created.png) | Profile saved appears and Demo Nikolay is accepting bookings. |
| 07 | OWNER | [team schedule](screenshots/07-owner-team-schedule.png) | The owner sees both synthetic appointments and their contact details. |
| 08 | OWNER | [service catalogue](screenshots/08-owner-service-catalogue.png) | The catalogue shows durations, prices and service-edit links. |
| 09 | OWNER | [service price edit](screenshots/09-owner-service-price-edit.png) | The service form contains the new price. |
| 10 | OWNER | [service saved](screenshots/10-owner-service-saved.png) | The catalogue shows 22.00 EUR; existing bookings retain their 20.00 EUR quote. |
| 11 | OWNER | [weekly hours edit](screenshots/11-owner-weekly-hours-edit.png) | The weekly-hours form contains the new opening time. |
| 12 | OWNER | [weekly hours saved](screenshots/12-owner-weekly-hours-saved.png) | Schedule saved is visible and the database stores Monday 10:00 opening. |
| 13 | OWNER | [days off range](screenshots/13-owner-days-off-range.png) | Both inclusive range endpoints are visible. |
| 14 | OWNER | [days off saved](screenshots/14-owner-days-off-saved.png) | The three dates are listed and stored; existing appointments remain unchanged. |
| 15 | BARBER | [home staff entry](screenshots/15-barber-home-staff-entry.png) | The public homepage exposes the Staff sign in link. |
| 16 | BARBER | [login form](screenshots/16-barber-login-form.png) | The sign-in form is ready to submit. |
| 17 | BARBER | [dashboard](screenshots/17-barber-dashboard.png) | The correct role dashboard is displayed. |
| 18 | BARBER | [own services edit](screenshots/18-barber-own-services-edit.png) | Only the intended bookable service remains checked. |
| 19 | BARBER | [own services saved](screenshots/19-barber-own-services-saved.png) | Services saved appears and the database contains only the Classic Haircut assignment. |
| 20 | BARBER | [weekly hours edit](screenshots/20-barber-weekly-hours-edit.png) | The weekly-hours form contains the new opening time. |
| 21 | BARBER | [weekly hours saved](screenshots/21-barber-weekly-hours-saved.png) | Schedule saved is visible and the database stores Monday 10:00 opening. |
| 22 | BARBER | [days off range](screenshots/22-barber-days-off-range.png) | Both inclusive range endpoints are visible. |
| 23 | BARBER | [days off saved](screenshots/23-barber-days-off-saved.png) | The three dates are listed and stored; existing appointments remain unchanged. |
| 24 | BARBER | [colleague schedule privacy](screenshots/24-barber-colleague-schedule-privacy.png) | The barber sees their own customer details; the colleague reservation says Booked with no customer contacts. |
| 25 | CLIENT | [homepage services](screenshots/25-client-homepage-services.png) | The public menu displays service descriptions, durations and prices. |
| 26 | CLIENT | [booking start](screenshots/26-client-booking-start.png) | The booking page opens with service, barber and date choices. |
| 27 | CLIENT | [service selected](screenshots/27-client-service-selected.png) | The service is selected and compatible options refresh. |
| 28 | CLIENT | [barber selected](screenshots/28-client-barber-selected.png) | The barber is selected and the calendar shows matching dates. |
| 29 | CLIENT | [date and available times](screenshots/29-client-date-and-available-times.png) | Available appointment times are displayed for the selected service, barber and date. |
| 30 | CLIENT | [time selected contact form](screenshots/30-client-time-selected-contact-form.png) | The contact form opens for the selected visit. |
| 31 | CLIENT | [contact details ready](screenshots/31-client-contact-details-ready.png) | The completed contact form is ready; no new appointment has been created yet. |
| 32 | CLIENT | [booking confirmed](screenshots/32-client-booking-confirmed.png) | You are booked in appears with the reservation summary; exactly one new appointment is persisted. |

The machine-readable manifest records every action, expected/actual result, image path and dimensions. core-manifest.json describes the two additional compact report captures. results.json records the focused final run without copying unrelated audit output.
