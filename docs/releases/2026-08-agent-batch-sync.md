# Sync guide: agent batch Aug 2026

How this release branch was rebuilt after the cloud agent could not push a complete GitHub branch.

## Branch

`cursor/release-agent-batch-9558` in:

- `RetailerCustomerPlatform`
- `retailer_ordereasy_njs`
- `customer_ordereasy_njs`

Recreated locally from `origin/main` by merging the good per-ticket branches (not from the incomplete MCP-uploaded GitHub release branch).

## Push

```bash
git push -u origin cursor/release-agent-batch-9558 --force-with-lease
```

`--force-with-lease` is required because GitHub already has a truncated `cursor/release-agent-batch-9558`. Do not use `--force`.

## PR titles (ready for review, base `main`)

- RCP: **Release: agent batch Aug 2026 (backend + docs)**
- Retailer: **Release: agent batch Aug 2026 (retailer)**
- Customer: **Release: agent batch Aug 2026 (customer)**

Cross-link all three. Ticket table lives in [2026-08-agent-batch.md](2026-08-agent-batch.md).

## Deploy order (after Vineet approves)

1. Merge RCP release PR first (KAN-78/79 APIs before retailer UI).
2. Merge both FE release PRs (parallel OK).
3. Open RCP PR `main` → `deploy/dev` (Oracle GHA).
4. Build FEs into `retailer_web_build` / `customer_web_build` and deploy Cloudflare Pages.
5. Rebase KAN-75 (#65) onto new `main`.
6. Only then mark Jira Done.

Do not merge closed broken uploads RCP #57 / #58.
