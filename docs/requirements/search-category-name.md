# Category name on retailer product search

- **Ticket:** [OE-291](https://vin8003.atlassian.net/browse/OE-291) · [snapshot](../tickets/OE-291.md)
- **Implementation:** EXTEND (echo existing `Product.category.name` on search)
- **Related:** [search-is-in-stock.md](search-is-in-stock.md) (OE-312), [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287), [search-barcode.md](search-barcode.md) (OE-290), [search-original-price.md](search-original-price.md) (OE-293), [search-product-group.md](search-product-group.md) (OE-295), [search-discounted-price.md](search-discounted-price.md) (OE-298), [search-is-featured.md](search-is-featured.md) (OE-299), [search-is-active.md](search-is-active.md) (OE-300), [search-is-available.md](search-is-available.md) (OE-303)

Retailer product search includes top-level `category_name` with the same value already returned by list/detail (`Product.category.name`). This is a field echo, not category CRUD. POS `no_page` already exposes the field.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `category_name` on list / detail serializers | EXISTING |
| `category_name` on POS `?no_page=true` row dict | EXISTING |
| `category_name` on `ProductSearchSerializer` | EXTEND (OE-291) |
| Category write APIs | Out of scope |

## API

| Method | Path | Who | `category_name` |
|--------|------|-----|-----------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail (`Product.category.name`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | EXISTING (POS uses `Uncategorized` when unset) |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

No category → `null` on search (same as the list getter). POS `no_page` keeps its existing `Uncategorized` sentinel; this slice does not retarget that row.

Retailer and public search querysets `select_related('category')` so the echo is one join, not per-row.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Category CRUD, POS Uncategorized rewrite, public catalog invent, inventory.adjust, timeline/OFD/khata/UPI/slots, pack write, FE, Jira Done, live `*.ordereasy.win`.
