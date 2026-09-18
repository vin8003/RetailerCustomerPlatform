# Optional is_hazmat on product list/detail

- **Ticket:** [OE-363](https://vin8003.atlassian.net/browse/OE-363) · [snapshot](../tickets/OE-363.md)
- **Implementation:** EXTEND (echo instance `is_hazmat` when the attribute exists)
- **Related:** list/detail field echoes; do not stack onto [search-is-featured.md](search-is-featured.md) Meta

Retailer product list and detail include top-level `is_hazmat` only when the product instance already has that attribute (`hasattr` / `getattr`). This is a read echo, not a Product column, migration, or write path.

Missing attribute → omit the key (do not invent `false`). Present `false` stays `false`. Present `null` stays `null`.

Do not add `is_hazmat` to serializer `Meta.fields`. Do not use model `_meta` to detect the field.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `is_hazmat` on Product model | Out of scope (no column on this tip) |
| `is_hazmat` on list / detail serializers | EXTEND (OE-363) — optional attribute echo |
| `is_hazmat` on `ProductSearchSerializer` Meta | Out of scope |
| `is_hazmat` on POS `?no_page=true` | Out of scope |
| Create/update write of `is_hazmat` | Out of scope |

## API

| Method | Path | Who | `is_hazmat` |
|--------|------|-----|-------------|
| GET | `/api/products/` | Authenticated retailer | Present only when instance has the attribute |
| GET | `/api/products/<id>/` | Authenticated retailer | Present only when instance has the attribute |
| GET | `/api/products/search/` | Authenticated retailer | Unchanged (no Meta add) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Unchanged |

Auth/tenancy unchanged. No extra query.

## Not in this change

`ProductSearchSerializer` Meta, POS `products/views.py`, Product model / migration, create/update serializers, cart, returns, ledger, FE, Jira Done, live `*.ordereasy.win`.
