# Product unit on POS no_page reads

- **Ticket:** [OE-286](https://vin8003.atlassian.net/browse/OE-286) · [snapshot](../tickets/OE-286.md)
- **Implementation:** EXTEND (echo existing `Product.unit` on POS `no_page`)

Retailer POS `GET /api/products/?no_page=true` includes top-level `unit` with the same value already returned by list/detail/search (`Product.unit`). This is a field echo, not a conversion engine.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.unit` on list / detail / search serializers | EXISTING |
| `unit` on POS `?no_page=true` row dict | EXTEND (OE-286) |
| Unit conversion, write APIs, default invent on read | Out of scope |

## API

| Method | Path | Who | `unit` |
|--------|------|-----|--------|
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same as list/detail (`Product.unit`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/search/` | Authenticated retailer | EXISTING |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Unchanged |

Empty or null `unit` stays empty/null. Reads do not invent `piece` unless that is the stored model value (the field default is still `piece` on create).

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU (absent / **404**).

## Not in this change

Unit conversion, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
