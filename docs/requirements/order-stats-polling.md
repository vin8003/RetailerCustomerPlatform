# Order/stats API polling

- **Ticket:** [KAN-20](https://vin8003.atlassian.net/browse/KAN-20) · [snapshot](../tickets/KAN-20.md)

`/api/orders/stats/` must not be hit in an unbounded render loop.

**Rules**

1. Client polling at most **once every 60 seconds**.
2. Prefer refresh on cashier events (order completed) over tight intervals.
3. Backend may cache stats (~30s) so bursts do not stampede the DB.

Unthrottled polling can pin CPU and exhaust the database during peak hours.
