# Optional `is_fragile` on product list/detail

- **Ticket:** [OE-362](https://vin8003.atlassian.net/browse/OE-362) · [snapshot](../tickets/OE-362.md)
- **Implementation:** EXTEND (optional echo of `Product.is_fragile` when the attribute exists)

Retailer product **list** and **detail** include top-level `is_fragile`. If the product has an `is_fragile` attribute, the stored value is echoed. If the attribute is missing (this stack: Product has no fragile column), or the value is null, the payload is `null`. False stays false. This is a field echo, not a packaging / delivery-handling model.

`is_fragile` is **not** added to `Meta.fields` (Avoid Meta). The key is injected in `to_representation` so serializers stay valid when the model column is absent.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| List / detail availability bools | EXISTING |
| Optional `is_fragile` on list / detail | EXTEND (OE-362) |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `?no_page=true` row dict | EXISTING — do not change |
| Product `is_fragile` column / write | Out of scope |

## API

| Method | Path | Who | `is_fragile` |
|--------|------|-----|--------------|
| GET | `/api/products/` | Authenticated retailer | `getattr(product, 'is_fragile', None)` |
| GET | `/api/products/<id>/` | Authenticated retailer | `getattr(product, 'is_fragile', None)` |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Same via shared list serializer |
| GET | `/api/products/retailer/<id>/<product_id>/` (public) | Customer / anonymous | Same via shared detail serializer |
| POST / PATCH | `/api/products/create/` · `/api/products/<id>/update/` | Authenticated retailer | Response uses detail serializer (same echo). Write body `is_fragile` is ignored. |
| Other list/detail consumers | Featured / deals / other lanes that reuse these serializers | Same optional key |

Missing attribute → `null`. Null stays null. False stays false. Do not invent fragility.

Write payloads may include `is_fragile`; it is ignored. The SKU is not changed. No model migration.

Unauthenticated retailer list/detail → **401**. Customer retailer list/detail → **403**. Tenant B cannot read tenant A's SKU (**404** / omitted).

The echo reads the already-loaded product instance. No extra product query.

## Not in this change

Product model / migration, search Meta, POS views, create/update Meta, cart, returns, ledger, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, FE, Jira Done, live `*.ordereasy.win`.
