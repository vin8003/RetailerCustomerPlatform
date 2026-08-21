---
name: jira-to-pr
description: >-
  Takes a Jira ticket through phased implementation to an opened GitHub PR with
  unit tests and review each phase and a full pytest suite before PR. Use when
  starting work from a Jira key (KAN-*), implementing a ticket end-to-end, or
  when the user asks for ticket-to-PR / jira-to-pr workflow.
---

# Jira → PR (backend)

## 1. Jira (work)

- Fetch issue via Atlassian MCP (`KAN-*`).
- Restate acceptance criteria; ask if unclear. Never invent scope.

## 2. Phase plan

- Break into ordered isolated steps (invoke `phased-delivery`).
- Note UT + negative cases per phase.
- Share the plan when useful; adjust if the user reorders/cuts scope.

## 3. GitHub (implementation)

- Branch named with `KAN-*`.
- **For each phase:**
  1. Implement only that phase
  2. Add/update unit tests (happy + negative/edge when relevant) under `<app>/tests/`
  3. Run focused tests, then full suite: `pytest`
  4. Mini-review the phase diff; only then start the next phase
- Before any commit: secret scan (see `git-hygiene`).
- Before push: `review-before-push` (includes full suite results).
- Open PR with Jira key in title/body.

## 4. Knowledge

- If behavior/runbook changed, update/add markdown (README or `docs/`).
- Call out GitBook sync if that is how docs are published.

## 5. Deploy

- Only if user asks → invoke `deploy-backend` (re-runs review + secret + pytest checks).

## 6. Close the loop

- Jira comment with PR/deploy links.
- Transition status only when the user wants it moved.
