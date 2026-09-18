# Brand name on cart line items

- **Ticket:** [OE-314](https://vin8003.atlassian.net/browse/OE-314) · [snapshot](../tickets/OE-314.md)
- **Implementation:** EXTEND (echo existing `Product.brand.name` on cart items)
- **Related:** [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287)

Customer cart line items include top-level `brand_name` with the same value already returned by product list/detail (`Product.brand.name`). This is a field echo, not brand CRUD or a checkout change.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `brand_name` on list / detail serializers | EXISTING |
| `brand_name` on public catalog list / detail | EXISTING |
| `brand_name` on `CartItemSerializer` | EXTEND (OE-314) |
| Brand write / FE ProductCard / barcode on cart | Out of scope |

## API

| Method | Path | Who | `brand_name` |
|--------|------|-----|--------------|
| GET | `/api/cart/?retailer_id=<id>` | Authenticated customer | Same as list/detail (`Product.brand.name`) |
| GET | `/api/cart/` | Authenticated customer | Same on each cart's `items` |
| POST | `/api/cart/add/` | Authenticated customer | Same on the returned cart `items` |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING |

No brand → `null` (same as list getter). Do not omit the key. `CartSerializer` prefetches items with `select_related('product', 'product__brand')` so the echo is one join, not per-row.

Unauthenticated → **401**. Retailer → **403**. Customer B cannot read customer A's cart lines.

## Not in this change

Barcode on cart, FE ProductCard, search Meta, POS, brand CRUD, checkout/UPI/slots/khata, Jira Done, live `*.ordereasy.win`.
