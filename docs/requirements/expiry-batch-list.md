# Expiring / expired batch list

- **Ticket:** [OE-210](https://vin8003.atlassian.net/browse/OE-210) · backlog `F-0125` (thin slice) · [snapshot](../tickets/OE-210.md)
- **Implementation:** EXTEND (`ProductBatch.expiry_date` + shop-scoped list read)
- **Depends on:** [product-batch-expiry.md](product-batch-expiry.md) (F-0030 dates)

Retailer-authenticated callers can list **this shop’s** active batches that expire on or before today+N and still have on-hand qty. Already-expired lots that are still on the shelf are included. There is no notify, push, or MIS report engine in this slice.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `ProductBatch.expiry_date`, saleable helpers, FIFO | EXISTING (OE-136) |
| `ProductBatchSerializer.expiry_date` | EXISTING |
| `GET /api/products/erp/expiring-batches/` | EXTEND — shop list read |
| Alerts, FE dashboards, `StockMovement`, full F-0125 MIS | Out of scope |

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/products/erp/expiring-batches/?days=N` | Authenticated retailer (owner or staff) | Active batches for **this shop** with `expiry_date <= localdate() + N` and `quantity > 0`. Default **N=30** when `days` is omitted. |

Rows reuse batch fields (`id`, `batch_number`, `barcode`, prices, `quantity`, `is_active`, `show_on_app`, `expiry_date`) plus `product_id` / `product_name`. Ordered by `expiry_date`, then id.

| Filter | Included | Excluded |
|--------|----------|----------|
| Dated, active, qty > 0, expiry ≤ today+N | yes | — |
| Already expired, still on-hand | yes | — |
| Null `expiry_date` | — | yes |
| `quantity = 0` or `is_active=false` | — | yes |
| Other shop / other tenant | — | empty list (never mixed) |

Invalid `days` (negative or non-integer) → **400**. Customer / non-retailer → **403**. Unauthenticated → **401**. No org/shop for the caller → **404**.

Query is one `ProductBatch` select with `select_related('product')`, always filtered by `retailer` and `retailer__organization`. No N+1 per row.

## Not in this change

Full F-0125 MIS, alerts, FE dashboards, `StockMovement` invent, OE-102, GST / #103, OE-149 notify, Jira Done, live `*.ordereasy.win`.
