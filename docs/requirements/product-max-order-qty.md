# Optional `max_order_qty` on product serializers

- **Ticket:** [OE-359](https://vin8003.atlassian.net/browse/OE-359) · [snapshot](../tickets/OE-359.md)
- **Implementation:** EXTEND (echo `max_order_qty` only when the instance has that attribute)
- **Related:** list/detail already expose `maximum_order_quantity` (`Product.maximum_order_quantity`). This key is a different, optional attribute — not an alias and not a Meta field.

Product list / detail / search may include top-level `max_order_qty` when the serialized instance has that attribute. `Product` has no `max_order_qty` column today, so live catalog rows omit the key. Detection uses `hasattr` — not model `_meta` and not serializer `Meta.fields`.

Null stays null. Integral decimals JSON as int (same shape as other optional qty reads).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `maximum_order_quantity` on list / detail | EXISTING |
| `max_order_qty` model field / migration | Out of scope |
| `max_order_qty` on list / detail / search via mixin | EXTEND (OE-359) |
| Serializer `Meta.fields` entry | Out of scope (avoid Meta) |
| POS `no_page`, writes, cart, orders | Out of scope |

## API

| Method | Path | Who | `max_order_qty` |
|--------|------|-----|-----------------|
| GET | `/api/products/` | Authenticated retailer | Present only if instance has `max_order_qty` |
| GET | `/api/products/<id>/` | Authenticated retailer | Present only if instance has `max_order_qty` |
| GET | `/api/products/search/` | Authenticated retailer | Present only if instance has `max_order_qty` |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Unchanged (hand-built row) |

## Not in this change

Model/migration, write serializers, POS `no_page`, cart, orders, FE, merge, Jira Done, live `*.ordereasy.win`.
