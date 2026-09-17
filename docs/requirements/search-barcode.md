# Barcode on retailer product search

- **Ticket:** [OE-290](https://vin8003.atlassian.net/browse/OE-290) · [snapshot](../tickets/OE-290.md)
- **Implementation:** EXTEND (echo existing `Product.barcode` on search)
- **Related:** [additional-barcodes-lookup.md](additional-barcodes-lookup.md) (OE-170 query match), [search-original-price.md](search-original-price.md) (OE-293), [search-product-group.md](search-product-group.md) (OE-295), [search-discounted-price.md](search-discounted-price.md) (OE-298), [search-is-featured.md](search-is-featured.md) (OE-299), [search-is-active.md](search-is-active.md) (OE-300)

Retailer product search includes top-level `barcode` with the same value already returned by list/detail/POS `no_page` (`Product.barcode`). This is a field echo, not barcode write and not additional-barcode invent.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `barcode` on list / detail serializers | EXISTING |
| `barcode` on POS `?no_page=true` row dict | EXISTING |
| `barcode` on `ProductSearchSerializer` | EXTEND (OE-290) |
| Additional barcodes in search **query** | EXISTING (OE-170) |
| `additional_barcodes` echo on search rows | Out of scope |
| Barcode write APIs | Out of scope |

## API

| Method | Path | Who | `barcode` |
|--------|------|-----|-----------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail/POS (`Product.barcode`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | EXISTING |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

Empty/null `Product.barcode` stays empty/null (same as list). No invented fallback.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

`additional_barcodes` echo, barcode write, public catalog invent, inventory.adjust, timeline/OFD/khata/UPI/slots, pack write, FE, Jira Done, live `*.ordereasy.win`.
