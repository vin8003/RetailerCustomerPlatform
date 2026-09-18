# Optional `is_returnable` on product detail

- **Ticket:** [OE-357](https://vin8003.atlassian.net/browse/OE-357) · [snapshot](../tickets/OE-357.md)
- **Implementation:** EXTEND (echo `is_returnable` on product detail only when the attribute exists)
- **Related:** [search-is-active.md](search-is-active.md) (search Meta is out of scope here)

Retailer and public **product detail** include top-level `is_returnable`. If the product has an `is_returnable` attribute, the stored bool is echoed. If the attribute is missing (this stack: Product has no `is_returnable` column), or the value is null, the payload is `null`. Present `false` stays `false`. This is a field echo, not a return-policy write or a new Product column.

`is_returnable` is **not** added to `ProductDetailSerializer.Meta.fields` (or list/search Meta). Detail injects the key in `to_representation` via `getattr`.

`ProductSearchSerializer` Meta and list/POS payloads do not gain this field.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product model `is_returnable` column | EXISTING if present; not invented here |
| Optional `is_returnable` on product detail | EXTEND (OE-357) |
| Search Meta / list / POS `no_page` / writes | Out of scope |

## API

| Method | Path | Who | `is_returnable` |
|--------|------|-----|-----------------|
| GET | `/api/products/<id>/` | Authenticated retailer | `optional_is_returnable(product)` — bool, or `null` if missing |
| GET | `/api/products/retailer/<id>/<id>/` (public detail) | Customer / anonymous | Same getter (shared detail serializer) |
| GET | `/api/products/search/` | Authenticated retailer | Not added (search Meta unchanged) |

Unauthenticated retailer detail → **401**. Customer on retailer detail → **403**. Other shop's product id → **404**.

## Not in this change

`ProductSearchSerializer` Meta, POS `products/views.py`, list/create/update serializers, model/migration invent, cart, returns, ledger, FE, Jira Done, live `*.ordereasy.win`.
