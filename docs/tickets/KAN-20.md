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

## Problem

Unbounded `/api/orders/stats/` from dashboard `useEffect` / leaked intervals. Retailer sidebar later used a 60s `setInterval` fallback.

## Fix

- Remove timer-based polling of `orders/stats/`.
- Fetch once on dashboard mount for the Orders pending badge.
- Refresh when FCM delivers `new_order` / `order_refresh` (`fcm_order_update`) or when the cashier updates an order locally (`order_stats_refresh`).
- Show the pending count on desktop Orders nav and mobile bottom Orders tab.
