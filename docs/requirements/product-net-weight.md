# Optional net weight on product catalog reads

- **Implementation:** EXTEND (optional echo of `Product.net_weight` when the attribute exists)
- **Related:** [search-original-price.md](search-original-price.md) (field-echo pattern), [search-is-active.md](search-is-active.md) (search Meta lock)

Retailer and public product **list / search / detail** include top-level `net_weight`. If the product instance has a `net_weight` attribute, the stored value is echoed. If the attribute is missing (this stack: Product has no `net_weight` column), or the value is null, the payload is `null`. This is a field echo, not a weight column / GST rebuild.

Do **not** declare `net_weight` on serializer `Meta.fields`. `ProductSearchSerializer` Meta is locked; the mixin injects the key in `to_representation`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list / detail / search identity scalars | EXISTING |
| Optional `net_weight` on list / search / detail | EXTEND (mixin, no Meta) |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `products/views.py` `?no_page=true` | EXISTING — do not change |
| Product `net_weight` column / write APIs | Out of scope |

## API

| Method | Path | Who | `net_weight` |
|--------|------|-----|--------------|
| GET | `/api/products/` | Authenticated retailer | `getattr(product, 'net_weight', None)` |
| GET | `/api/products/search/` | Authenticated retailer | same, via mixin (not Meta) |
| GET | `/api/products/<id>/` | Authenticated retailer | same |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Additive via shared list serializer |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer |
| GET | `/api/products/retailer/<id>/<product_id>/` (public) | Customer / anonymous | Additive via shared detail serializer |

Missing attribute → `null`. Null stays null. Do not invent a weight.

Write payloads may include `net_weight`; it is ignored. The SKU is not changed.

Unauthenticated retailer list/search → **401**. Customer retailer-search → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Product `net_weight` column, search Meta, POS views, create/update write, cart, returns, purchase invoice, ledger, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live `*.ordereasy.win`.
