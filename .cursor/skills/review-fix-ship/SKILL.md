---
name: review-fix-ship
description: >-
  End-to-end ship workflow: dispatch a code-review subagent, fix every issue
  (Critical, Important, and Minor), ensure a Jira ticket and KAN-* branch exist,
  update local docs, commit, run the full test suite, and open a PR to main.
  Use when the user asks to review and ship, review-fix-commit-pr, or after
  finishing implementation and before merge.
---

# Review → fix → ship

One workflow from implemented code to an open PR. **Fix every review item**, including Minor — do not defer nits.

## 1. Ticket and branch

1. **Jira key** — from branch name, `docs/tickets/KAN-*.md`, or user message.
2. **No ticket?** — create one via Atlassian MCP (`createJiraIssue` in project `KAN`). Restate scope in the issue body; never invent acceptance criteria beyond what the user or code implies.
3. **Branch** — must be named with the key (`feature/KAN-46-…`, `kan-46-…`, etc.). Create and check it out if still on `main`.
4. **Fetch issue** — read acceptance criteria from Jira; align fixes and docs to them.

## 2. Code review (subagent)

Get SHAs for the review range:

```bash
BASE_SHA=$(git merge-base HEAD origin/main)   # or origin/main if no local commits yet
HEAD_SHA=$(git rev-parse HEAD)
```

If work is **uncommitted**, tell the reviewer to inspect `git diff` and `git diff --cached` against `BASE_SHA` in addition to `BASE_SHA..HEAD_SHA`.

Dispatch a **generalPurpose** subagent using [code-reviewer.md](code-reviewer.md). Fill placeholders:

| Placeholder | Value |
|-------------|--------|
| `{DESCRIPTION}` | One-line summary of what was built |
| `{PLAN_OR_REQUIREMENTS}` | Jira acceptance criteria + `docs/requirements/*.md` or ticket snapshot |
| `{BASE_SHA}` | merge-base with `main` |
| `{HEAD_SHA}` | current `HEAD` |

Reviewer output must include **Strengths**, **Issues** (Critical / Important / Minor), **Recommendations**, and **Assessment**.

## 3. Fix everything

Work through issues in order: **Critical → Important → Minor**.

- Fix all items; user asked for Minor fixes too — no "fix later" list unless the reviewer was wrong (push back with reasoning).
- Re-run focused tests after each logical fix group.
- If a fix changes behavior, update tests in the same pass.

## 4. Local docs

Update durable knowledge when behavior or runbooks changed:

| Change type | Update |
|-------------|--------|
| New/changed behavior | `docs/requirements/<topic>.md` |
| Ticket context | `docs/tickets/KAN-*.md` snapshot |
| Index | `docs/requirements/README.md`, `docs/tickets/README.md` |

Match front-matter and linking style of sibling ticket pages. Do not delete Confluence/GitBook references.

## 5. Pre-commit gates

1. **Secret skim** — scan the full diff for `.env*`, keys, PEM, Bearer tokens, `AKIA…`, passwords in logs. **Block** if found.
2. **Full test suite** — backend: `pytest` (must be green; cite command + result). **Block** on failure.
3. **Diff summary** — short note of files, risks, and test outcome for the user.

## 6. Commit

On the `KAN-*` branch only (never `main` / `deploy/dev`):

```bash
git add <relevant files>
git commit -m "$(cat <<'EOF'
feat(KAN-NNN): short imperative summary

Why this change matters in one sentence.
EOF
)"
```

Follow existing repo commit style (`feat`, `fix`, `chore` + Jira key).

## 7. Push and PR

1. `git push -u origin HEAD`
2. Open PR **into `main`** via `gh pr create`:
   - Title: `feat(KAN-NNN): …` (or `fix` / `chore`)
   - Body: Summary bullets, test plan checklist, link to Jira `https://vin8003.atlassian.net/browse/KAN-NNN`
3. **Jira comment** — PR URL via Atlassian MCP (`addCommentToJiraIssue`). Transition status only if the user asked.

## 8. Report

```
## Shipped
- Jira: KAN-NNN (link)
- Branch: …
- PR: …
- Review: N issues fixed (C/I/M breakdown)
- Tests: pytest — green
- Docs: …
```

## Wire-ins

- Implementation phases before this skill: `phased-delivery`, `jira-to-pr`
- Deploy to Oracle only when explicitly asked: `deploy-backend`
- Do **not** skip the subagent review because the diff is small

## Never

- Ignore Critical or Important review items
- Defer Minor items without user opt-out
- Push or open PR with a red test suite
- Commit secrets or `.env`
- Push directly to `main` or `deploy/dev`
- Invent Jira scope when criteria are unclear — ask first
