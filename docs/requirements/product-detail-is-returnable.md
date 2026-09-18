# Optional `is_returnable` on product detail

- **Ticket:** [OE-357](https://vin8003.atlassian.net/browse/OE-357) · [snapshot](../tickets/OE-357.md)
- **Implementation:** EXTEND (echo `is_returnable` on product detail only when the attribute exists)
- **Related:** [search-is-active.md](search-is-active.md) (search Meta is out of scope here)

`ProductDetailSerializer` may include top-level `is_returnable` as a bool when the product instance already exposes that attribute. This is a field echo, not a new Product column, migration, or return-policy write.

If the attribute is missing, the key is omitted — do not invent `false`. If the attribute exists and is `false`, the key stays and the value is `false`.

`ProductSearchSerializer` Meta and list/POS payloads do not gain this field.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product model `is_returnable` column | EXISTING if present; not invented here |
| `is_returnable` on `ProductDetailSerializer` when attribute exists | EXTEND (OE-357) |
| Search Meta / list / POS `no_page` / writes | Out of scope |

## API

| Method | Path | Who | `is_returnable` |
|--------|------|-----|-----------------|
| GET | `/api/products/<id>/` | Authenticated retailer | Bool when attribute exists; omitted when missing |
| GET | `/api/products/retailer/<id>/<id>/` (public detail) | Customer / anonymous | Same serializer rule |
| GET | `/api/products/search/` | Authenticated retailer | Not added (search Meta unchanged) |

Unauthenticated retailer detail → **401**. Customer on retailer detail → **403**. Other shop's product id → **404**.

## Not in this change

`ProductSearchSerializer` Meta, POS `products/views.py`, list/create/update serializers, model/migration invent, cart, returns, ledger, FE, Jira Done, live `*.ordereasy.win`.
