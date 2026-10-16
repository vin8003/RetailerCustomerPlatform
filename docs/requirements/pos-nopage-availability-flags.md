# Featured / available / in-stock flags on POS no_page reads

- **Ticket:** [OE-302](https://vin8003.atlassian.net/browse/OE-302) · [snapshot](../tickets/OE-302.md)
- **Implementation:** EXTEND (echo existing list/detail bools on POS `no_page`)
- **Related:** [search-is-featured.md](search-is-featured.md) (OE-299), [search-is-active.md](search-is-active.md) (OE-300), [pos-nopage-unit.md](pos-nopage-unit.md) (OE-286)

Retailer POS `GET /api/products/?no_page=true` includes top-level `is_featured`, `is_available`, and `is_in_stock` with the same values already returned by list/detail. This is a field echo, not featured write, availability write, or a stock engine.

`is_featured` and `is_available` are `Product` boolean fields. `is_in_stock` is the existing model property (parent-bulk delegates to parent; untracked mirrors `is_available`; tracked is `quantity > 0`).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `is_featured` / `is_available` / `is_in_stock` on list / detail | EXISTING |
| Those keys on POS `?no_page=true` row dict | EXTEND (OE-302) |
| Those keys on `ProductSearchSerializer` | Unchanged this ticket (`is_featured` already on search via OE-299; `is_available` / `is_in_stock` not added here) |
| Featured / availability write, FE badge, queryset filters | Out of scope |

## API

| Method | Path | Who | Flags |
|--------|------|-----|-------|
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same as list/detail |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/search/` | Authenticated retailer | Unchanged this ticket |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Unchanged |

`false` stays `false` (keys present). Null handling mirrors the model / list serializers.

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU (absent / **404**).

## Not in this change

Search Meta, featured/availability write, FE, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`.
