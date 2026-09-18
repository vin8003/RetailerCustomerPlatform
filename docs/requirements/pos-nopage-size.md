# Optional size on POS no_page reads

- **Implementation:** EXTEND (echo existing `Product.size` on POS `no_page` **only if that column already exists**)
- **Related:** [pos-nopage-unit.md](pos-nopage-unit.md) (OE-286)

Retailer POS `GET /api/products/?no_page=true` may include top-level `size` with the stored model value **when `Product` already has a `size` column**. This is a field echo, not a new size/color matrix and not a default invent.

This tree's `Product` model has **no** `size` column. Reads therefore **omit** the key. Do not invent `size` from `specifications`, master attributes, unit, or a hardcoded pack label.

If a later migration adds `Product.size`, POS `no_page` will start emitting the stored value (empty/null passthrough). List/detail/search stay unchanged until those serializers are explicitly extended.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.size` model column | **Not in tree** — do not add |
| `size` on list / detail / search serializers | Not present |
| `size` on POS `?no_page=true` row dict | EXTEND — attach only when the column exists |
| Size/color matrix, write APIs, default invent on read | Out of scope |

## API

| Method | Path | Who | `size` |
|--------|------|-----|--------|
| GET | `/api/products/?no_page=true` | Authenticated retailer | Present only if `Product.size` already exists; otherwise omitted |
| GET | `/api/products/` | Authenticated retailer | Unchanged (no invented `size`) |
| GET | `/api/products/<id>/` | Authenticated retailer | Unchanged |
| GET | `/api/products/search/` | Authenticated retailer | Unchanged |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Unchanged |

When the column exists, empty or null `size` stays empty/null (same passthrough as `unit`). Reads do not invent `M` / `500ml` / `piece`.

POS query flags (`no_page`, `is_active`, `is_featured`, `is_seasonal`, `is_available`, `in_stock`) are unchanged.

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU (absent / **404**).

## Not in this change

`Product.size` migration, specifications promotion, master-attribute mapping, search Meta, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
