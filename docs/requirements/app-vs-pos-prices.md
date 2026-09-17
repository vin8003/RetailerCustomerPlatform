# App vs POS prices

- **Ticket:** [OE-106](https://vin8003.atlassian.net/browse/OE-106) · backlog `F-0023` · [snapshot](../tickets/OE-106.md)
- **Implementation:** EXTEND (`Product.app_price` + existing `Product.price`)
- **Depends on:** [shop-staff-roles.md](shop-staff-roles.md) (`catalog.price`), existing product / cart / POS serializers

The same SKU can have a **store / POS** price different from the **owned-app** price. Stock stays one ATP pool (`Product.quantity` / saleable). This is not a PriceList engine (that is [OE-104](https://vin8003.atlassian.net/browse/OE-104) / F-0022) and does not add a marketplace connector.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.price` / `ProductBatch.price` as store / POS list | EXISTING |
| `Product.app_price` (null = fall back to store price) | EXTEND |
| Customer catalog + cart read resolved app price | EXTEND |
| POS checkout and POS `no_page` list keep store price | EXISTING store field, EXTEND `app_price` on retailer payload |
| `catalog.price` permission for `app_price` mutate | EXTEND (catalog v8) |
| `OrgAuditLog` `channel_price` on `app_price` change | EXTEND |
| One on-hand / saleable pool | EXISTING |
| PriceList / org+list+sku matrix, marketplace channel, FE matrix UI | Out of scope |

## Resolution

| Channel | Selling price |
|---------|----------------|
| Store / POS / retailer product APIs | `Product.price` (or batch `price` when a batch is sold) |
| Owned app / public catalog / customer cart | `Product.app_price` if set, else store price |

Customer / public payloads do **not** include `app_price` or the store-only list. Retailer payloads include both `price` (store) and `app_price`.

The same rewrite applies to customer-facing leftovers: wishlist `product_price`, `group_variants[].price`, and nested `batches[].price` when `app_price` is set. No batch-level app price and no PriceList matrix.

There is no marketplace channel in this repo. A later marketplace connector must not read the store or app list of another channel; do not invent a connector here.

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/products/` and `/api/products/<id>/` | Retailer JWT | Store `price` + `app_price` |
| GET | `/api/products/?no_page=true` | Retailer JWT (POS) | Store `price` + `app_price` |
| GET | `/api/products/search/` | Retailer JWT | Store `price` + `app_price` + `discounted_price` (store selling alias; OE-298) |
| GET | `/api/products/retailer/<retailer_id>/…` | Public / customer | Resolved app selling price as `price` (and `discounted_price` on search; OE-298); no `app_price` field |
| POST | `/api/products/erp/pos-checkout/` | Retailer JWT | Validates against store `price` |
| POST | `/api/cart/add/` | Customer JWT | `unit_price` from app resolution |
| POST | `/api/orders/place/` | Customer JWT | `OrderItem` stamps cart/channel `unit_price` (not store `Product.price`) |
| PUT/PATCH | `/api/products/<id>/update/` | `catalog.price` when `app_price` **differs** | **403** if missing; echo OK |
| POST | `/api/products/create/` | `catalog.price` when `app_price` is set | **403** if missing |
| PATCH | `/api/products/bulk-update/` | `catalog.price` when any item `app_price` **differs** | **403** (nothing applied for that gate) |

Store `price` edits stay on the existing product update path and do **not** require `catalog.price` (cashiers can still change the counter price; see OE-127). Excel / scanner upload is ungated for `app_price` in this slice.

Cross-tenant product ids stay **404** (retailer-scoped get).

## Audit

Changing `app_price` appends `OrgAuditLog` (`object_type=channel_price`) with before/after `store_price` and `app_price`.

## Not in this change

F-0022 org+list+sku PriceLists, wholesale customer lists, marketplace connector, channel-specific ATP / reservations (F-0029), FE price-matrix UI, live `*.ordereasy.win`.
