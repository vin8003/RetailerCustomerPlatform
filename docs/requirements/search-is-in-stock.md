# In-stock flag on retailer product search

- **Ticket:** [OE-312](https://vin8003.atlassian.net/browse/OE-312) · [snapshot](../tickets/OE-312.md)
- **Implementation:** EXTEND (echo existing `Product.is_in_stock` on search)
- **Related:** [search-is-available.md](search-is-available.md) (OE-303), [search-is-active.md](search-is-active.md) (OE-300), [search-is-featured.md](search-is-featured.md) (OE-299), [search-discounted-price.md](search-discounted-price.md) (OE-298), [search-product-group.md](search-product-group.md) (OE-295), [search-is-seasonal.md](search-is-seasonal.md) (OE-294), [search-original-price.md](search-original-price.md) (OE-293), [search-category-name.md](search-category-name.md) (OE-291), [search-barcode.md](search-barcode.md) (OE-290), [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287)

Retailer product search includes top-level `is_in_stock` with the same value already returned by list/detail (`Product.is_in_stock`). This is a field echo, not stock write, inventory.adjust, or a catalog-visibility change.

`is_in_stock` is a model `@property`, not a DB column. List/detail already declare it as a read-only `BooleanField`. Search uses the same declaration (not a `SerializerMethodField`). No extra `select_related` — retailer search already selects `parent_bulk_product`.

POS `?no_page=true` does not include `is_in_stock`. This change does not add it there.

Public `GET /api/products/retailer/<id>/` and public `GET /api/products/retailer/<id>/search/` still filter `is_available=True`. They do not filter `is_in_stock`. An available SKU with `is_in_stock=false` stays on public list/search; the search serializer echoes `false`. This change does not invent stock math.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `is_in_stock` on list / detail serializers | EXISTING |
| `is_in_stock` on POS `?no_page=true` row dict | Out of scope (not present) |
| Public list / public-search queryset `is_available=True` | EXISTING (unchanged; not an `is_in_stock` filter) |
| `is_in_stock` on `ProductSearchSerializer` | EXTEND (OE-312) |
| Stock write / inventory.adjust / FE | Out of scope |

## API

| Method | Path | Who | `is_in_stock` |
|--------|------|-----|---------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail (`Product.is_in_stock`); queryset is not stock-filtered |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Not present (unchanged) |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING (active + available only) |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

`false` stays `false` (same as list). Do not omit the key when false.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Stock write/admin, invent stock math, FE, POS `no_page` field add, search queryset change, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`.
