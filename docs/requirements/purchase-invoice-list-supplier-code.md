# Optional `supplier_code` on purchase-invoice list

- **Implementation:** EXTEND (`PurchaseInvoiceListSerializer` on `GET /api/products/erp/purchase-invoices/`)
- **Related:** [suppliers.md](suppliers.md) (PI list already exposes `supplier_name`)

`GET /api/products/erp/purchase-invoices/` rows may include `supplier_code` when `PurchaseInvoice` or the joined `Supplier` has that attribute. This stack has no `supplier_code` column — do not invent one or add a migration. Missing attribute and stored null pass through as `null`. Empty string stays empty.

List only. Create / retrieve / update keep `PurchaseInvoiceSerializer` and do not persist a client-sent `supplier_code`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `GET /erp/purchase-invoices/` + `supplier_name` | EXISTING |
| `select_related('supplier')` on the list queryset | EXISTING |
| Optional list `supplier_code` via `getattr` | EXTEND |
| `PurchaseInvoice.supplier_code` / `Supplier.supplier_code` column | Out of scope |
| ProductSearchSerializer Meta, cart, returns | Out of scope |

## API

| Method | Path | Who | Field |
|--------|------|-----|-------|
| GET | `/api/products/erp/purchase-invoices/` | Shop retailer JWT | `supplier_code` = invoice attr if present, else supplier attr if present, else `null` |
| GET / POST / PATCH | same viewset, non-list | Shop retailer JWT | no `supplier_code` key |

Unauthenticated → **401**. Other shop's invoice detail stays **404**. List stays shop-scoped.

No extra supplier query: the list queryset already joins `supplier`. Query budget unchanged (4 fixed + 4 per invoice).

## Not in this change

`ProductSearchSerializer` Meta, POS `products/views.py`, cart serializers, `returns/serializers.py` / `returns/views.py`, PI line `unit` (OE-310), ledger, FE, Jira Done, live `*.ordereasy.win`.
