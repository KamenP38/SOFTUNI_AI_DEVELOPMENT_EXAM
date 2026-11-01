# Project agent instructions

## Project scope
- Work in `softuni_ai_development_exam`. Keep project agents and installed skills here; do not install them globally.
- This repository is being prepared for a single-shop Django booking website.
- Keep the architecture simple: Django, server-rendered templates, CSS, plain JavaScript and PostgreSQL. Reuse existing project conventions once code is present; do not add frameworks or services without a concrete requirement.

## Agents and workflow
- `dev-agent` (`.codex/agents/dev-agent.toml`) owns application implementation and maintainability.
- `test-agent` (`.codex/agents/test-agent.toml`) owns backend tests, frontend verification and regression reporting.
- For application development tasks, delegate implementation to `dev-agent`, then delegate independent verification to `test-agent`. Give each a bounded task and acceptance criteria. Avoid concurrent edits to the same files.
- Start delegated agents with fresh context containing only this repository's instructions and the relevant task requirements, rather than inheriting the full conversation history.
- For documentation or setup-only tasks, use only the work needed to validate the change.
- Both agents must read `.agents/skills/django-patterns/SKILL.md` before Django work. Apply relevant guidance to the actual stack; its examples do not mandate DRF, Redis, Celery or a new project layout.
- If named custom agents are unavailable in the current client, pass the corresponding TOML `developer_instructions` to a regular sub-agent explicitly; do not silently drop the role instructions.

## Product requirements
- Administrators create barber accounts with usernames and passwords and view/edit every barber's schedule.
- Barbers view/edit their own schedules and view other barbers' schedules without gaining permission to edit them. Viewing a colleague's schedule does not by itself authorize disclosure of customer contact details.
- Clients see services, durations and prices and book a service, barber, date and time. A phone number is mandatory and must be validated on the server.
- Enforce permissions on the server, protect customer data, and prevent overlapping bookings, including concurrent submissions.

## Delivery standard
- Make focused changes with clear names, small functions and comments explaining non-obvious decisions. Document setup changes and business rules needed by future developers.
- Use the project's virtual environment and existing tooling. Never use real customer data or production databases for tests.
- Report what changed, checks actually run, their results and any unverified behavior. Do not claim tests passed when they were skipped or unavailable.
