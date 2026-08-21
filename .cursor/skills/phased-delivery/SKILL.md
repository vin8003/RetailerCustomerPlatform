---
name: phased-delivery
description: >-
  Breaks non-trivial backend work into ordered phases with implement → unit
  tests → focused plus full pytest → mini-review per phase. Use when starting a
  multi-step ticket, feature, or refactor, or when work spans more than one
  concern and big-bang delivery must be avoided.
---

# Phased delivery (backend)

## Start

1. Split work into phases that each leave the tree green (e.g. model → API → edge cases → docs).
2. Share the phase list when useful; adjust if the user reorders/cuts scope.

## Per-phase loop (required)

1. **Implement** only that phase's files/behavior.
2. **Unit tests** for that phase (happy + ≥1 negative/edge when relevant) under `<app>/tests/`.
3. **Run tests** — focused tests for the touched area, then full suite: `pytest`. Fix before declaring the phase done.
4. **Mini-review** — short summary of the phase diff (correctness, readability, secrets). Do not start the next phase until verified.
5. **Optional** — commit the phase alone when the user wants commits.

## Forbidden

- Big-bang: implement everything, then one giant test run and one giant review at the end.

## Wire-ins

- `jira-to-pr` step 2 = phase plan; step 3 = this loop.
- Do not mark merge-ready or push until the final phase's full suite is green and `review-before-push` has been satisfied.
