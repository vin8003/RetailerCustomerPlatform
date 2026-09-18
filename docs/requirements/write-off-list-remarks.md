# Optional remarks on write-off list rows

- **Ticket:** [OE-358](https://vin8003.atlassian.net/browse/OE-358) · [snapshot](../tickets/OE-358.md)
- **Implementation:** EXTEND (optional echo of `ProductInventoryLog.remarks` when the attribute exists)
- **Related:** [damage-expiry-write-off.md](damage-expiry-write-off.md) (OE-141 list / ledger), [inventory-ledger-product-identity.md](inventory-ledger-product-identity.md)

`GET /api/products/erp/inventory-ledger/` write-off list rows include top-level `remarks`. If the inventory log has a `remarks` attribute, the stored value is echoed. If the attribute is missing (this stack: log has `reason` only), or the value is null, the payload is `null`. Empty string stays empty. Do not invent remarks from `reason`.

This is a field echo, not a new write-off note column or POST body field.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Ledger row `id` / qty / `reason` / identity | EXISTING (OE-141 / OE-315) |
| Optional `remarks` on write-off / ledger list rows | EXTEND (OE-358) |
| `ProductInventoryLog.remarks` column | Out of scope — do not add |
| Write-off POST / `write_off_stock` | EXISTING — do not accept remarks |
| `ProductSearchSerializer` Meta / POS views | EXISTING — do not change |

## API

| Method | Path | Who | `remarks` |
|--------|------|-----|-----------|
| GET | `/api/products/erp/inventory-ledger/` | Shop retailer JWT | `getattr(log, 'remarks', None)` |

Missing attribute → `null`. Null stays null. Empty stays empty. Do not copy `reason` into `remarks`.

`product_id` and/or `reason` still required. Other shop's `product_id` is **404**. Shop-wide `?reason=` stays this shop only.

Unauthenticated → **401**. Customer / no retailer profile → **403**.

Write-off `POST /api/products/<id>/write-off/` does not accept a `remarks` body field. Extra keys in the POST body are ignored. No column is created.

Query is one `ProductInventoryLog` select with `select_related('product', 'created_by')` after the retailer-profile get. Remarks is an attribute on that row — no extra query.

## Not in this change

`ProductInventoryLog` migration, write-off POST persist, FE write-off list (OE-326), ledger `unit` (OE-350), search Meta, POS `products/views.py`, cart, returns, purchase invoice, inventory.adjust / pack write, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`.
