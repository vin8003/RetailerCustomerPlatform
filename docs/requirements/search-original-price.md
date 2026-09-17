# Original price on retailer product search

- **Ticket:** [OE-293](https://vin8003.atlassian.net/browse/OE-293) · [snapshot](../tickets/OE-293.md)
- **Implementation:** EXTEND (echo existing `Product.original_price` on search)
- **Related:** [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287), [search-barcode.md](search-barcode.md) (OE-290), [search-category-name.md](search-category-name.md) (OE-291)

Retailer product search includes top-level `original_price` with the same value already returned by list/detail/POS `no_page` (`Product.original_price`). This is a field echo, not price write.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `original_price` on list / detail serializers | EXISTING |
| `original_price` on POS `?no_page=true` row dict | EXISTING |
| `original_price` on `ProductSearchSerializer` | EXTEND (OE-293) |
| Price write APIs | Out of scope |

## API

| Method | Path | Who | `original_price` |
|--------|------|-----|------------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail/POS (`Product.original_price`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | EXISTING |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

Null/absent `Product.original_price` stays `null` (same as list). Do not coerce to `0`.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Price write, margin invent, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, FE, Jira Done, live `*.ordereasy.win`.
