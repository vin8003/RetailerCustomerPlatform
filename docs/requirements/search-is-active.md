# Active flag on retailer product search

- **Ticket:** [OE-300](https://vin8003.atlassian.net/browse/OE-300) · [snapshot](../tickets/OE-300.md)
- **Implementation:** EXTEND (echo existing `Product.is_active` on search)
- **Related:** [search-is-in-stock.md](search-is-in-stock.md) (OE-312), [search-is-available.md](search-is-available.md) (OE-303), [search-is-featured.md](search-is-featured.md) (OE-299), [search-discounted-price.md](search-discounted-price.md) (OE-298), [search-product-group.md](search-product-group.md) (OE-295), [search-is-seasonal.md](search-is-seasonal.md) (OE-294), [search-original-price.md](search-original-price.md) (OE-293), [search-category-name.md](search-category-name.md) (OE-291), [search-barcode.md](search-barcode.md) (OE-290), [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287), [inactive-product-edit.md](inactive-product-edit.md) (KAN-62)

Retailer product search includes top-level `is_active` with the same value already returned by list/detail/POS `no_page` (`Product.is_active`). This is a field echo, not active write, admin, or a catalog-visibility change.

Retailer `GET /api/products/search/` and public `GET /api/products/retailer/<id>/search/` still filter `is_active=True`. Inactive SKUs stay on list/detail/POS; the search serializer echoes `false` when given an inactive instance.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `is_active` on list / detail serializers | EXISTING |
| `is_active` on POS `?no_page=true` row dict | EXISTING |
| Search / public-search queryset `is_active=True` | EXISTING (unchanged) |
| `is_active` on `ProductSearchSerializer` | EXTEND (OE-300) |
| Active write / admin / FE | Out of scope |

## API

| Method | Path | Who | `is_active` |
|--------|------|-----|-------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail/POS (`Product.is_active`); queryset still active-only |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | EXISTING |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING (active + available only) |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

`false` stays `false` (same as list). Do not omit the key when false.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Active write/admin, FE, search queryset change, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`.
