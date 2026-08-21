---
name: deploy-backend
description: >-
  Deploys the OrderEasy Django backend by opening an approved PR into deploy/dev,
  which triggers GitHub Actions SSH deploy to the Oracle VM. Use when the user
  asks to deploy the backend, ship BE to Oracle, or run the backend deploy workflow.
---

# Deploy backend

## Preconditions

- User **explicitly** asked to deploy.
- Intended commit is ready on a feature branch (not committed directly on `deploy/dev`).

## Checklist

1. **Confirm intent** — restate that merging into `deploy/dev` runs `.github/workflows/deploy.yml` → SSH → `/home/ubuntu/deploy.sh` on Oracle.
2. **review-before-push** — follow `.cursor/skills/review-before-push/SKILL.md`:
   - Diff vs base
   - Secret skim
   - Full suite: `pytest` must be green (cite outcome)
   - Present findings; wait for confirmation unless already ordered in this turn
3. **PR into `deploy/dev`** — push feature branch, open PR targeting `deploy/dev`. Do **not** push `deploy/dev` directly.
4. **Wait for review** — do not merge immediately; allow time for feedback.
5. **Merge only with ≥1 approval** — never merge with zero approvals (see `pr-workflow` rule).
6. **Report** — PR URL, merge SHA, GitHub Action status if available.

## Never

- Deploy without an explicit ask
- Commit/push directly to `deploy/dev` or `main`/`master`
- Merge without approval
- Skip review / secret skim / full pytest
- Force-push `deploy/dev`
