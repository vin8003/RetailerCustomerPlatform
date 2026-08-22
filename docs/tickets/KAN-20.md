---
id: KAN-20
title: Order/stats API continuous polling
knowledge_class: durable
owning_repo: retailer_ordereasy_njs
durable_docs:
  - docs/requirements/order-stats-polling.md
jira: https://vin8003.atlassian.net/browse/KAN-20
confluence: https://vin8003.atlassian.net/wiki/spaces/KAN/pages/294938/KAN-20+Order+Stats+API+Continuous+Polling+Fix
gitbook: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/kan-20-order-stats-api-polling-fix
---

# KAN-20 Order/stats API polling

Work snapshot. Durable: [order-stats-polling.md](../requirements/order-stats-polling.md).

Unbounded `/api/orders/stats/` from dashboard `useEffect` / leaked intervals. Cap at 60s, prefer event-driven refresh, optional ~30s backend cache.
