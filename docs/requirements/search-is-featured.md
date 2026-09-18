# Featured flag on retailer product search

- **Ticket:** [OE-299](https://vin8003.atlassian.net/browse/OE-299) · [snapshot](../tickets/OE-299.md)
- **Implementation:** EXTEND (echo existing `Product.is_featured` on search)
- **Related:** [pos-nopage-availability-flags.md](pos-nopage-availability-flags.md) (OE-302), [search-is-active.md](search-is-active.md) (OE-300), [search-discounted-price.md](search-discounted-price.md) (OE-298), [search-product-group.md](search-product-group.md) (OE-295), [search-is-seasonal.md](search-is-seasonal.md) (OE-294), [search-original-price.md](search-original-price.md) (OE-293), [search-category-name.md](search-category-name.md) (OE-291), [search-barcode.md](search-barcode.md) (OE-290), [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287)

Retailer product search includes top-level `is_featured` with the same value already returned by list/detail (`Product.is_featured`). This is a field echo, not featured write, admin, or a customer-app badge.

POS `?no_page=true` now also echoes `is_featured` (OE-302). OE-299 did not add it there.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `is_featured` on list / detail serializers | EXISTING |
| `is_featured` on POS `?no_page=true` row dict | EXTEND (OE-302; out of scope for OE-299) |
| `is_featured` on `ProductSearchSerializer` | EXTEND (OE-299) |
| Featured write / admin / FE badge | Out of scope |

## API

| Method | Path | Who | `is_featured` |
|--------|------|-----|---------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail (`Product.is_featured`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same as list/detail (OE-302) |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

`false` stays `false` (same as list). Do not omit the key when false.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Featured write/admin, FE badge, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`. POS `no_page` `is_featured` is OE-302.
