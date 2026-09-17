# Brand name on search and POS no_page reads

- **Ticket:** [OE-287](https://vin8003.atlassian.net/browse/OE-287) · [snapshot](../tickets/OE-287.md)
- **Implementation:** EXTEND (echo existing `Product.brand.name` on search + POS `no_page`)

Retailer product search and POS `GET /api/products/?no_page=true` include top-level `brand_name` with the same value already returned by list/detail (`Product.brand.name`). This is a field echo, not brand CRUD.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `brand_name` on list / detail serializers | EXISTING |
| `brand_name` on `ProductSearchSerializer` | EXTEND (OE-287) |
| `brand_name` on POS `?no_page=true` row dict | EXTEND (OE-287) |
| Brand write / public catalog invent | Out of scope |

## API

| Method | Path | Who | `brand_name` |
|--------|------|-----|--------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail (`Product.brand.name`) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same as list/detail (`Product.brand.name`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Unchanged (already has `brand_name`) |

No brand → `null` (same as list getter). POS `select_related` includes `brand` so the echo is one join, not per-row.

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU (absent / **404**).

## Not in this change

Brand CRUD, public catalog invent, inventory.adjust, timeline/OFD/khata/UPI/slots, pack write, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
