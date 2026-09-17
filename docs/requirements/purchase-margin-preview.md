# Purchase margin% preview (draft or last PI cost)

- **Ticket:** [OE-118](https://vin8003.atlassian.net/browse/OE-118) · backlog `F-0046` (thin slice) · [snapshot](../tickets/OE-118.md)
- **Implementation:** EXTEND (`Product.price`, `Product.purchase_price`, `PurchaseItem.purchase_price`)
- **Depends on:** [compare-supplier-cost.md](compare-supplier-cost.md) (OE-112 last-PI helpers) and [shop-staff-roles.md](shop-staff-roles.md) (`purchasing.terms` as purchase-role)

Purchase-role staff can read a **margin% preview** for a shop SKU: selling price versus the draft SKU cost or, if that is unset, the latest purchase-invoice unit cost. There is no threshold policy, override, PO document, or block in this slice.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.price`, `Product.purchase_price`, `PurchaseItem.purchase_price` | EXISTING |
| OE-112 last-PI / purchase-role helpers | EXISTING |
| `GET /api/products/erp/products/<id>/margin-preview/` | EXTEND — computed preview read |
| Threshold policy, override audit, PO create block | Out of scope (full F-0046 / hold OE-102) |

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/products/erp/products/<product_id>/margin-preview/` | Purchase-role (`purchasing.terms`; org owner is implicit admin) | `{ product_id, selling_price, cost, cost_source, margin_percent }` |

Cost resolution:

1. **draft** — `Product.purchase_price` when it is not `NULL` (including stored `0.00`)
2. **last_pi** — latest `PurchaseItem.purchase_price` for this shop SKU (`invoice_date`, then `created_at`, then item id)
3. **missing** — both absent → `cost` and `margin_percent` are **`null`**. The API does not invent `0`.

`selling_price` is store `Product.price`. `margin_percent` is `(selling_price - cost) / selling_price * 100` (2 decimal places). Zero sell → `margin_percent` null. `cost_source` is `draft`, `last_pi`, or `null`.

Cross-tenant SKU → **404**. Cashier / customer / other non-purchase callers → **403**. Unauthenticated → **401**.

At most one `PurchaseItem` query (skipped when draft cost is set). No N+1.

## Not in this change

Full F-0046 (threshold policy, override audit, PO/GRN block), OE-102, GST / #103, FE matrix, notify, Jira Done, live `*.ordereasy.win`.
