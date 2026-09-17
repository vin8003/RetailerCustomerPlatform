# Purchase margin% preview (draft or last PI cost)

- **Ticket:** [OE-118](https://vin8003.atlassian.net/browse/OE-118) · backlog `F-0046` (preview) · [OE-169](https://vin8003.atlassian.net/browse/OE-169) · backlog `F-0071` (catalog field) · [snapshots](../tickets/OE-118.md)
- **Implementation:** EXTEND (`Product.price`, `Product.purchase_price`, `PurchaseItem.purchase_price`)
- **Depends on:** [compare-supplier-cost.md](compare-supplier-cost.md) (OE-112 last-PI helpers) and [shop-staff-roles.md](shop-staff-roles.md) (`purchasing.terms` as purchase-role)

Purchase-role staff can read a **margin% preview** for a shop SKU: selling price versus the draft SKU cost or, if that is unset, the latest purchase-invoice unit cost. There is no threshold policy, override, PO document, or block in this slice.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.price`, `Product.purchase_price`, `PurchaseItem.purchase_price` | EXISTING |
| OE-112 last-PI / purchase-role helpers | EXISTING |
| `GET /api/products/erp/products/<id>/margin-preview/` | EXTEND — computed preview read (OE-118) |
| Retailer catalog list / detail / search `margin_percent` | EXTEND — same math on purchase-role reads (OE-169) |
| Threshold policy, override audit, PO/POS till block | Out of scope (full F-0046 / F-0071) |

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/products/erp/products/<product_id>/margin-preview/` | Purchase-role (`purchasing.terms`; org owner is implicit admin) | `{ product_id, selling_price, cost, cost_source, margin_percent }` |
| GET | Retailer product list / detail / search | Purchase-role | Same `margin_percent` (2 d.p.). Cashiers and public **omit** the field. POS `no_page` till payload is unchanged. |

Cost resolution:

1. **draft** — `Product.purchase_price` when it is not `NULL` (including stored `0.00`)
2. **last_pi** — latest `PurchaseItem.purchase_price` for this shop SKU (`invoice_date`, then `created_at`, then item id)
3. **missing** — both absent → `cost` and `margin_percent` are **`null`**. The API does not invent `0`.

`selling_price` is store `Product.price`. `margin_percent` is `(selling_price - cost) / selling_price * 100` (2 decimal places). Zero sell → `margin_percent` null. `cost_source` is `draft`, `last_pi`, or `null`.

Cross-tenant SKU → **404** on detail / absent from list. Dedicated preview: cashier / customer → **403**. Catalog list/detail/search: non-purchase **omits** `margin_percent` (catalog stays readable). Unauthenticated → **401**.

At most one `PurchaseItem` query on the preview (skipped when draft cost is set). Catalog lists batch last-PI costs in one query. No N+1.

## Not in this change

Full F-0046 / F-0071 (threshold policy, override audit, PO/GRN block, POS till block / PIN), OE-102, GST / #103, FE matrix, notify, Jira Done, live `*.ordereasy.win`.
