---
name: review-before-push
description: >-
  Runs a pre-push review checklist including secret skim, deploy side effects,
  and requiring a green full pytest suite before any git push. Use when about to
  push, when the user asks to push or deploy, or before updating a remote branch
  or opening/updating a PR.
---

# Review before push (backend)

Run this checklist before **any** `git push` (feature branch, PR update, or `deploy/dev`).

## Steps

1. **Range** — `git log` / `git diff` against upstream (or base branch). Summarize commits and files.
2. **Secret skim** — scan that diff for `.env*`, keys, `service_account`, PEM/KEY material, Bearer tokens, `AKIA…`, private-key headers, suspicious secrets. Stop and warn if found.
3. **Full test suite** — confirm `pytest` was run green for this repo; cite command + outcome. If not run yet, run it now. **Block push on failure.**
4. **Deploy side effects** — call out if target is `deploy/dev` (triggers GHA → Oracle SSH deploy).
5. **Present findings** to the user: what changed, risks, tests, negatives checked, deploy implication.
6. **Push only** after confirmation, or if the user already ordered push/deploy in the same turn.

## Output template

```
## Pre-push review
- Branch → remote:
- Commits:
- Risk areas:
- Secrets: clean / BLOCKED
- pytest: green (summary) / BLOCKED
- Deploy side effect: none | deploy/dev → Oracle
- Ready to push? awaiting confirmation
```
