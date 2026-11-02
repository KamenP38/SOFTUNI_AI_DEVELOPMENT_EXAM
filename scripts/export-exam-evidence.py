"""Copy only a successful exam run's real browser screenshots into submission docs."""
import json
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".artifacts" / "cypress"
OUTPUT = ROOT / "docs" / "exam-evidence"


def export():
    results = json.loads((ARTIFACTS / "results.json").read_text(encoding="utf-8"))
    assert results["totalPassed"] == 3 and results["totalFailed"] == 0
    assert len(results["runs"]) == 1
    run = results["runs"][0]
    assert run["spec"]["relative"].replace("\\", "/") == "cypress/e2e/exam-flows.cy.js"
    shots = {Path(item["path"]).name: item for item in run["screenshots"]}
    metadata = json.loads((ARTIFACTS / "exam-evidence-metadata.json").read_text(encoding="utf-8"))
    assert [item["ordinal"] for item in metadata] == list(range(1, 33))
    (OUTPUT / "screenshots").mkdir(parents=True, exist_ok=True)

    def copy_shot(item):
        source = Path(shots[item["filename"]]["path"])
        destination = OUTPUT / "screenshots" / source.name
        shutil.copy2(source, destination)
        width, height = struct.unpack(">II", destination.read_bytes()[16:24])
        return {**item, "path": destination.relative_to(ROOT).as_posix(),
                "width": width, "height": height,
                "dimensions": {"width": width, "height": height},
                "language": "en", "viewport": {"width": 1200, "height": 800}}

    manifest = [copy_shot(item) for item in metadata]
    core = [copy_shot(item) for item in [
        {"role": "OWNER", "filename": "core-owner-created.png",
         "step_title": "New barber accepts bookings",
         "action": "Create Demo Nikolay through the owner form.",
         "expected_outcome": "A new barber card shows Accepting bookings and assigned services.",
         "actual_outcome": "The new card shows Accepting bookings, Classic Haircut and Beard Trim."},
        {"role": "CLIENT", "filename": "core-client-confirmed.png",
         "step_title": "Successful client reservation",
         "action": "Submit the completed contact form for the selected visit.",
         "expected_outcome": "A booking confirmation shows the visit details.",
         "actual_outcome": "You are booked in appears with service, barber, date, time, duration and price."},
    ]]
    summary = {"command": "npm run test:e2e -- cypress/e2e/exam-flows.cy.js",
               "passed": results["totalPassed"], "failed": results["totalFailed"],
               "pending": results["totalPending"], "skipped": results["totalSkipped"],
               "browser": results["browserName"], "browser_version": results["browserVersion"],
               "cypress_version": results["cypressVersion"], "database": "isolated synthetic SQLite",
               "frozen_application_date": "2026-11-15", "viewport": "1200x800", "language": "en",
               "screenshots": len(manifest), "compact_core_captures": len(core),
               "tests": [{"title": test["title"][-1], "state": test["state"]} for test in run["tests"]]}
    for item in core:
        item["name"] = item["filename"].removesuffix(".png")
    envelope = {"run": summary, "screenshots": manifest, "core_screenshots": core}
    for filename, value in [("manifest.json", envelope), ("core-manifest.json", core), ("results.json", summary)]:
        (OUTPUT / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Exam walkthrough evidence", "",
             "All appointment, account and service data shown here is synthetic demonstration data. "
             "Names prefixed Demo, test-only phone values and example.invalid email addresses do not identify real customers. "
             "The public website's fixed shop branding/contact section remains visible in homepage captures.", "",
             "The three independent Cypress tests use real browser clicks, typed forms and server responses. "
             "Each test starts with freshly seeded data. Owner and barber start on the homepage, click its footer Staff sign in link, "
             "and submit credentials in the UI. Client starts with the public service menu. No programmatic login or URL shortcut is used.", "",
             "**Result: 3 passed, 0 failed, 0 pending, 0 skipped.** "
             "Cypress 16.2.1 / Electron 146, English UI, 1200 × 800 desktop viewport, "
             "isolated SQLite database on loopback port 8766, application clock frozen at 15 November 2026. "
             "The 32 numbered images and 2 compact report images are native browser captures, with real panel/viewport crops and masked passwords.", "",
             "Run from the repository root:", "", "```powershell",
             summary["command"], ".venv\\Scripts\\python.exe scripts/export-exam-evidence.py", "```", "",
             "## Coverage and database evidence", "",
             "| Role | UI actions | Database assertions |", "| --- | --- | --- |",
             "| Owner | Homepage → login → dashboard → new barber with services/hours → schedule → catalogue price edit → weekly hours → inclusive day-off range | User/barber created, password hashed, 2 service assignments, 6 working days; new price persists while old appointment quotes remain; hours and all 3 days off persist |",
             "| Barber | Homepage → login → dashboard → own services → own hours → inclusive days off → colleague schedule | Only selected service assigned; Monday opening changes; all 3 days off persist; existing appointments retained; colleague customer details and cancel control absent |",
             "| Client | Homepage services → booking → service → barber → calendar date → time → contact details → confirmation | No business writes before confirmation; exactly 1 new appointment with expected barber, service, date/time, contact data, price and duration; other business tables unchanged |", "",
             "This focused successful-flow suite does not re-test Bulgarian/mobile layouts, invalid inputs, cancellation, "
             "other service-selection orders or PostgreSQL concurrent-overlap constraints. These screenshots are not a claim of exhaustive coverage. "
             "The earlier audit findings remain in docs/ui-audit.md; this run does not fix or supersede them. "
             "No uncaught browser exception or application console.error occurred in the passing run. "
             "Initial capture-only failures were corrected: scrolling a short page and choosing a hidden responsive header button. "
             "The final workflow uses the visible homepage booking button.", "",
             "The previous audit results, screenshot index, console log and server log were preserved under "
             ".artifacts/cypress/pre-exam before running this spec.", "",
             "## Numbered walkthrough", "", "| # | Role | Step and evidence | Expected and observed result |",
             "| --- | --- | --- | --- |"]
    for item in manifest:
        lines.append(f'| {item["ordinal"]:02d} | {item["role"]} | [{item["step_title"]}](screenshots/{item["filename"]}) | {item["actual_outcome"]} |')
    lines += ["", "The machine-readable manifest records every action, expected/actual result, image path and dimensions. "
              "core-manifest.json describes the two additional compact report captures. "
              "results.json records the focused final run without copying unrelated audit output.", ""]
    (OUTPUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    export()
