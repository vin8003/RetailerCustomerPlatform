# Brand name on purchase-return line items

- **Ticket:** [OE-352](https://vin8003.atlassian.net/browse/OE-352) · [snapshot](../tickets/OE-352.md)
- **Implementation:** EXTEND (echo existing `Product.brand.name` on purchase-return items)
- **Related:** [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287), [suppliers.md](suppliers.md) (OE-100)

Purchase-return line items include optional top-level `brand_name` with the same value already returned by retailer product list/detail (`Product.brand.name`) when the related product exists. This is a field echo, not brand CRUD or a return write-policy change.

No product, or a product with no brand → `null` (same as the list getter). Do not invent a brand from supplier, invoice, or notes.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Purchase-return item `product` / `product_name` / qty / price | EXISTING |
| `brand_name` on list / detail serializers | EXISTING |
| `brand_name` on `PurchaseReturnItemSerializer` | EXTEND (OE-352) |
| Sales-return items, search Meta, POS `no_page` | Out of scope |

## API

| Method | Path | Who | `brand_name` |
|--------|------|-----|--------------|
| GET | `/api/returns/purchase/` | Shop retailer JWT | Nested `items[].brand_name` = list `brand_name` |
| GET | `/api/returns/purchase/<id>/` | Shop retailer JWT | Same |
| POST | `/api/returns/purchase/` | Shop retailer JWT | Create response echoes product brand; body `brand_name` is ignored |

Unauthenticated → **401**. Other shop's return id is **404**. Shop list stays this shop only.

Query is one purchase-return select with `prefetch_related` of items `select_related('product', 'product__brand', 'batch')` after the retailer-profile get. No N+1 per row.

## Not in this change

`SalesReturnItemSerializer` (OE-313), `ProductSearchSerializer` Meta, POS `products/views.py`, purchase invoice serializers, cart, ledger, FE, brand CRUD, Jira Done, live `*.ordereasy.win`.
