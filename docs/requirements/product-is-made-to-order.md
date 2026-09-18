# Optional is_made_to_order on product reads

- **Implementation:** EXTEND (echo `Product.is_made_to_order` on list / detail / search **only if the model field exists**)
- **Related:** [search-is-featured.md](search-is-featured.md), [search-is-seasonal.md](search-is-seasonal.md)

Retailer product **reads** may include top-level `is_made_to_order` when `Product` actually has that field. This repo's `Product` model does not declare it yet, so current payloads **omit** the key. Do not add the name to serializer `Meta.fields` — a missing model field would raise at import/bind time.

When the field exists, `false` stays `false` (do not omit). Null stays `null` (do not invent `false`).

This is a field echo, not a made-to-order write path, inventory policy, or catalog rebuild.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product` flags (`is_active`, `is_featured`, `is_seasonal`, `is_available`) | EXISTING |
| `Product.is_made_to_order` model field / migration | Missing — do not invent |
| `is_made_to_order` on list / detail / search via `to_representation` | EXTEND (only if field exists) |
| `Meta.fields` entry, POS `no_page` hand-built dict, create/update write | Out of scope |
| FE badge / lead-time / inventory skip | Out of scope |

## API

| Method | Path | Who | `is_made_to_order` |
|--------|------|-----|--------------------|
| GET | `/api/products/` | Authenticated retailer | Present only if the model field exists |
| GET | `/api/products/<id>/` | Authenticated retailer | Same |
| GET | `/api/products/search/` | Authenticated retailer | Same (shared mixin; not a Meta field) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Unchanged (hand-built POS dict) |

Public list / detail / search inherit the same mixin when they share those serializers.

Unauthenticated / customer / tenancy rules are unchanged. No live `*.ordereasy.win` in tests — dummy objects only.

## Not in this change

Model/migration invent, `Meta.fields`, POS `no_page`, create/update write, inventory.adjust, timeline/OFD/khata/UPI/slots, pack write, FE, Jira Done, live `*.ordereasy.win`.
