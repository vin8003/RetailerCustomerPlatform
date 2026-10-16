# Order/stats API polling

- **Ticket:** [KAN-20](https://vin8003.atlassian.net/browse/KAN-20) · [snapshot](../tickets/KAN-20.md)

`/api/orders/stats/` must not be hit in an unbounded render loop or a repeating timer.

**Rules**

1. Retailer UI fetches stats **once on dashboard mount** (to show the current pending-order badge).
2. After that, refresh **only on events**: FCM `new_order` / `order_refresh` (`fcm_order_update`) or a local cashier status change (`order_stats_refresh`).
3. Do **not** poll on a timer (including a 60s fallback).
4. Do **not** cache stats responses without invalidating on new/updated orders — a stale cache would hide the badge after FCM fires.

Unthrottled polling can pin CPU and exhaust the database during peak hours.
