# Optional expiry_date on inventory-ledger rows

- **Implementation:** EXTEND (echo `expiry_date` only when `ProductInventoryLog` has that field)
- **Related:** [inventory-ledger-product-identity.md](inventory-ledger-product-identity.md), [product-batch-expiry.md](product-batch-expiry.md)

`GET /api/products/erp/inventory-ledger/` rows echo `expiry_date` **only when** `ProductInventoryLog` declares that column. This stack has no log-level `expiry_date` — payloads **omit** the key. Do not invent a date from `ProductBatch` or a default.

When the field exists: stored date is echoed; null stays `null`. The key is not declared on any serializer `Meta.fields` (a missing column must not crash bind).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Ledger identity / qty / reason / `batch_id` | EXISTING (OE-315 / OE-141) |
| `ProductBatch.expiry_date` | EXISTING (OE-136) — not the ledger source |
| `ProductInventoryLog.expiry_date` | Absent on this stack |
| Ledger row `expiry_date` when the log field exists | EXTEND |
| `ProductSearchSerializer` Meta / cart | Out of scope |

## API

| Method | Path | Who | Expiry |
|--------|------|-----|--------|
| GET | `/api/products/erp/inventory-ledger/` | Shop retailer JWT | Include `expiry_date` only if the log model has the field |

Auth/tenancy unchanged: unauthenticated **401**, customer / no retailer profile **403**, other shop's `product_id` **404**. Query stays one `ProductInventoryLog` select with `select_related('product', 'created_by')`.

## Not in this change

`ProductSearchSerializer` Meta, cart, POS `products/views.py`, log-column migration, batch-date invent, writes, FE, Jira Done, live `*.ordereasy.win`.
