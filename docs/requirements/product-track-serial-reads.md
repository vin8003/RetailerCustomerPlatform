# Optional track_serial on product reads

- **Implementation:** EXTEND (echo `Product.track_serial` on list / detail / search **only if the model field exists**)
- **Related:** [search-is-active.md](search-is-active.md) (optional catalog flags), [saleable-quantity-reads.md](saleable-quantity-reads.md)

Retailer product **reads** may include top-level `track_serial` when `Product` actually has that field. This repo's `Product` model does not declare it yet, so current payloads **omit** the key. Do not add the name to serializer `Meta.fields` — a missing model field would raise at import/bind time.

When the field exists, `false` stays `false` (do not omit). Null stays `null` (no invented `false`). This is a field echo, not a serial-number ledger, IMEI capture, or write path.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product` columns (qty, `track_inventory`) | EXISTING |
| `Product.track_serial` model field / migration | Missing — do not invent |
| `track_serial` on list / detail / search via `to_representation` | EXTEND (only if field exists) |
| `Meta.fields` entry, POS `no_page` hand-built dict, create/update write | Out of scope |
| Serial / IMEI ledger, FE toggle, scan capture | Out of scope |

## API

| Method | Path | Who | `track_serial` |
|--------|------|-----|----------------|
| GET | `/api/products/` | Authenticated retailer | Present only if the model field exists |
| GET | `/api/products/<id>/` | Authenticated retailer | Same |
| GET | `/api/products/search/` | Authenticated retailer | Same (shared mixin; not a Meta field) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Unchanged (hand-built POS dict) |

Unauthenticated / customer / tenancy rules are unchanged. No live `*.ordereasy.win` in tests — dummy objects only.

## Not in this change

Model/migration invent, `Meta.fields`, POS `no_page`, create/update write, serial ledger, FE, Jira Done, live `*.ordereasy.win`.
