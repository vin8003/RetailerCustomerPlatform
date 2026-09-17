# Product group on search and POS no_page reads

- **Ticket:** [OE-295](https://vin8003.atlassian.net/browse/OE-295) · [snapshot](../tickets/OE-295.md)
- **Implementation:** EXTEND (echo existing `Product.product_group` on search + POS `no_page`)
- **Related:** [group-variants-reads.md](group-variants-reads.md) (OE-192), [search-is-seasonal.md](search-is-seasonal.md) (OE-294), [search-original-price.md](search-original-price.md) (OE-293), [search-category-name.md](search-category-name.md) (OE-291), [search-barcode.md](search-barcode.md) (OE-290), [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287), [search-discounted-price.md](search-discounted-price.md) (OE-298), [search-is-featured.md](search-is-featured.md) (OE-299)

Retailer product search and POS `GET /api/products/?no_page=true` include top-level `product_group` with the same value already returned by list/detail (`Product.product_group`). This is a field echo, not a group matrix and not variant SKU invent. Sibling `group_variants` already ships (OE-192).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `product_group` on list / detail serializers | EXISTING |
| `group_variants` on list / search / POS `no_page` | EXISTING (OE-192) |
| `product_group` on `ProductSearchSerializer` | EXTEND (OE-295) |
| `product_group` on POS `?no_page=true` row dict | EXTEND (OE-295) |
| Group CRUD / size-color matrix / SKU invent | Out of scope |

## API

| Method | Path | Who | `product_group` |
|--------|------|-----|-----------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail (`Product.product_group`) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same as list/detail (`Product.product_group`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

Empty/null `Product.product_group` stays empty/null (same as list). Do not invent a fallback. No extra `select_related` is required — this is a column on `Product`.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Group CRUD/matrix, variant SKU invent, FE, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`.
