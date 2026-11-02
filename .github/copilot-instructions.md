# Repository instructions for GitHub Copilot

Follow the root `AGENTS.md` for project scope, requirements and development/testing practices.

## Agents
- Use `.github/agents/dev-agent.agent.md` for application implementation.
- Use `.github/agents/test-agent.agent.md` for independent backend and frontend verification.
- These profiles preserve the instructions in `.codex/agents/`. Keep corresponding profiles consistent when changing role instructions.
- No model is pinned: use the model selected in Copilot.

## Repository-local skills
Copilot discovers the existing skills in `.agents/skills/`; use those shared files directly.
- Read `.agents/skills/django-patterns/SKILL.md` before Django work.
- For UI test authoring, read `.agents/skills/cypress-author/SKILL.md` and its required references.
- Keep testing isolated with synthetic data, verify UI outcomes and database changes/non-changes, and report failures, skipped checks and suspicious behavior honestly.

If custom-agent delegation is unavailable, read and follow the corresponding `.github/agents/*.agent.md` role instructions directly.
