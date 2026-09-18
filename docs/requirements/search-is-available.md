# Available flag on retailer product search

- **Ticket:** [OE-303](https://vin8003.atlassian.net/browse/OE-303) · [snapshot](../tickets/OE-303.md)
- **Implementation:** EXTEND (echo existing `Product.is_available` on search)
- **Related:** [search-is-in-stock.md](search-is-in-stock.md) (OE-312), [search-is-active.md](search-is-active.md) (OE-300), [search-is-featured.md](search-is-featured.md) (OE-299), [search-discounted-price.md](search-discounted-price.md) (OE-298), [search-product-group.md](search-product-group.md) (OE-295), [search-is-seasonal.md](search-is-seasonal.md) (OE-294), [search-original-price.md](search-original-price.md) (OE-293), [search-category-name.md](search-category-name.md) (OE-291), [search-barcode.md](search-barcode.md) (OE-290), [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287), [pos-saleable-products.md](pos-saleable-products.md) (OE-190)

Retailer product search includes top-level `is_available` with the same value already returned by list/detail (`Product.is_available`). This is a field echo, not availability write, admin, or a catalog-visibility change.

POS `?no_page=true` does not include `is_available`. This change does not add it there.

Public `GET /api/products/retailer/<id>/` and public `GET /api/products/retailer/<id>/search/` still filter `is_available=True`. Unavailable SKUs stay on retailer list/detail/search; the search serializer echoes `false` when given an unavailable instance. Retailer search queryset does not filter `is_available`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `is_available` on list / detail serializers | EXISTING |
| `is_available` on POS `?no_page=true` row dict | Out of scope (not present) |
| Public list / public-search queryset `is_available=True` | EXISTING (unchanged) |
| `is_available` on `ProductSearchSerializer` | EXTEND (OE-303) |
| Availability write / admin / FE | Out of scope |

## API

| Method | Path | Who | `is_available` |
|--------|------|-----|----------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail (`Product.is_available`); queryset is not availability-filtered |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Not present (unchanged) |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING (active + available only) |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

`false` stays `false` (same as list). Do not omit the key when false.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Availability write/admin, FE, POS `no_page` field add, search queryset change, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`.
