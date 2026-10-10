# Compare supplier cost (last PI cost by supplier)

- **Ticket:** [OE-112](https://vin8003.atlassian.net/browse/OE-112) · backlog `F-0045` (thin slice) · [snapshot](../tickets/OE-112.md)
- **Implementation:** EXTEND (`PurchaseInvoice` / `PurchaseItem.purchase_price` + `supplier`)
- **Depends on:** [suppliers.md](suppliers.md) (F-0041) and [shop-staff-roles.md](shop-staff-roles.md) (`purchasing.terms` as purchase-role)

Purchase-role staff can read the **latest unit cost per supplier** for a shop SKU from existing purchase-invoice lines. There is no quote table, PO document, or separate cost model in this slice.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `PurchaseInvoice.supplier` + `PurchaseItem.purchase_price` | EXISTING |
| `GET /api/products/erp/products/<id>/last-supplier-costs/` | EXTEND — read of that history |
| PO / GRN / quotes, FE compare matrix, invented cost models | Out of scope (hold OE-102) |

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/products/erp/products/<product_id>/last-supplier-costs/` | Purchase-role (`purchasing.terms`; org owner is implicit admin) | `{ product_id, suppliers: [{ supplier_id, supplier_name, last_cost, invoice_id, invoice_date }] }`. Latest line per supplier by `invoice_date`, then `created_at`, then item id. Higher-cost suppliers stay in the list. |

Missing history is **`suppliers: []`**. The API does not invent `0`. A stored `0.00` line is real history and is returned.

Cross-tenant SKU → **404**. Cashier / customer / other non-purchase callers → **403**. Unauthenticated → **401**.

Query is one `PurchaseItem` select with `select_related('invoice', 'invoice__supplier')`. No N+1 per supplier.

## Not in this change

PO invent, quote invent, FE compare UI, reorder_level (OE-149), GST / #103, Jira Done, live `*.ordereasy.win`.

See also: [purchase-margin-preview.md](purchase-margin-preview.md) (OE-118 SKU margin% from draft-or-last PI cost).
