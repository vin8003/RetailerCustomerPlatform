# Product identity on inventory-ledger rows

- **Ticket:** [OE-315](https://vin8003.atlassian.net/browse/OE-315) · [snapshot](../tickets/OE-315.md)
- **Implementation:** EXTEND (echo existing product list identity on ledger rows)
- **Related:** [damage-expiry-write-off.md](damage-expiry-write-off.md) (OE-141 ledger filter), [expiry-batch-list.md](expiry-batch-list.md) (`product_id` / `product_name` on neighboring ERP rows)

`GET /api/products/erp/inventory-ledger/` rows include the same SKU identity already returned by retailer product list: `product_id` (list `id`), `product_name` (list `name`), `barcode` (list `barcode`). This is a field echo, not a new identity model, SKU code, or write path.

Null or empty `Product.barcode` stays `null` / `""`. Do not invent a `sku` column — Product has none; list identity is `id` + `name` + `barcode`. Ledger `id` remains the log id.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Ledger row `id` / qty / reason / `created_by` | EXISTING |
| `?product_id=` / `?reason=` filter, 404 / 400 / 403 | EXISTING (OE-141) |
| Product list `id` / `name` / `barcode` | EXISTING |
| Neighboring ERP `product_id` / `product_name` (expiring batches) | EXISTING (OE-210) |
| Ledger `product_id` / `product_name` / `barcode` | EXTEND (OE-315) |
| POS `no_page`, search Meta, FE, write paths | Out of scope |

## API

| Method | Path | Who | Identity |
|--------|------|-----|----------|
| GET | `/api/products/erp/inventory-ledger/` | Shop retailer JWT | Same SKU as list: `product_id` = list `id`, `product_name` = list `name`, `barcode` = list `barcode` |
| GET | `/api/products/` | Authenticated retailer | EXISTING list identity |

`product_id` and/or `reason` still required. Other shop's `product_id` is **404**. Shop-wide `?reason=` stays this shop only.

Unauthenticated → **401**. Customer / no retailer profile → **403**.

Query is one `ProductInventoryLog` select with `select_related('product', 'created_by')` after the retailer-profile get. No N+1 per row.

## Not in this change

POS `products/views.py`, `ProductSearchSerializer` Meta, cart, returns, purchase invoice, customers, orders, inventory.adjust / pack write, timeline/OFD/khata/UPI/slots, FE, Jira Done, live `*.ordereasy.win`.
