# GitBook / Confluence migration history

Preserve this folder. It records what already happened. Do not treat GitBook as the source of truth going forward.

Canonical knowledge: [`../DOCUMENTATION.md`](../DOCUMENTATION.md).

## Track A — Confluence → GitBook (ticket docs)

- Org: `ordereasy` (`Uytui5skXVecXruzm1yN`)
- Site: `ordereasy Docs` (`site_y3rLP`)
- Space: `iu06pIi3CiBqpw30jhyU`
- Change request: `UdehX5ZKSYUJHJ8N8KuF`
- Policy: **copy, don’t replace**. Confluence not deleted. Jira gained GitBook links; Confluence links kept.
- 18 of 24 open KAN issues had Confluence pages and were copied.
- Nesting quirk: KAN-16–KAN-20 are top-level GitBook pages, not under “Open Jira Ticket Docs”.
- Site was **not** published to a public hostname.

See [MANIFEST.json](MANIFEST.json) and [url_map.json](url_map.json).

## Track B — Git knowledge base → GitBook

- Source: this repo `docs/` on `main`
- Visuals commit: `429dbfc`
- GitBook section: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/platform-knowledge-base
- Change request: `PuPcLVEfle3Xbjoa29Ed`

## Phase 2 — Git as source of truth (this change)

GitBook free plan is not suitable as the team docs platform (multi-account). GitBook remains an **optional presentation layer**.

- Ticket Confluence bodies copied into [`../tickets/`](../tickets/).
- Durable rules extracted into `requirements/`, `07-KEY-FLOWS/`, `decisions/`.
- Jira should also point at Git ticket snapshots; Confluence and GitBook links stay.

## Do not

- Delete Confluence
- Remove Confluence links from Jira
- Delete GitBook org/pages
- Publish the GitBook site as part of docs chores
- Destroy this migration record
