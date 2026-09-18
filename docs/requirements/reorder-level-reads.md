# Optional reorder_level on product reads

- **Ticket:** [OE-149](https://vin8003.atlassian.net/browse/OE-149) · backlog `F-0034` (thin slice) · [snapshot](../tickets/OE-149.md)
- **Implementation:** EXTEND (echo `Product.reorder_level` on list / detail / search **only if the model field exists**)
- **Related:** [product-batch-expiry.md](product-batch-expiry.md) (OE-149 batch `is_expired`), [saleable-quantity-reads.md](saleable-quantity-reads.md)

Retailer product **reads** may include top-level `reorder_level` when `Product` actually has that field. This repo's `Product` model does not declare it yet, so current payloads **omit** the key. Do not add the name to serializer `Meta.fields` — a missing model field would raise at import/bind time.

When the field exists, null stays `null` (no invented `0`). `0` is a real threshold and is echoed. Quantity-style JSON: integral Decimals become ints.

This is a field echo, not a low-stock filter, alert, or write path. The existing `?low_stock=true` cutoff (`quantity <= 10`) is unchanged.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product` columns (qty, track, min/max order) | EXISTING |
| `Product.reorder_level` model field / migration | Missing — do not invent |
| `?low_stock=true` hardcoded `quantity <= 10` | EXISTING, unchanged |
| `reorder_level` on list / detail / search via `to_representation` | EXTEND (only if field exists) |
| `Meta.fields` entry, POS `no_page` hand-built dict, create/update write | Out of scope |
| Push / email / SMS / FE dashboard | Out of scope |

## API

| Method | Path | Who | `reorder_level` |
|--------|------|-----|-----------------|
| GET | `/api/products/` | Authenticated retailer | Present only if the model field exists |
| GET | `/api/products/<id>/` | Authenticated retailer | Same |
| GET | `/api/products/search/` | Authenticated retailer | Same (shared mixin; not a Meta field) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Unchanged (hand-built POS dict) |

Unauthenticated / customer / tenancy rules are unchanged. No live `*.ordereasy.win` in tests — dummy objects only.

## Not in this change

Model/migration invent, `Meta.fields`, POS `no_page`, create/update write, low-stock filter rewrite, notify/alerts, FE, Jira Done, live `*.ordereasy.win`.
