# Optional shelf life on product list/detail

- **Implementation:** EXTEND (optional echo of `Product.shelf_life_days` when the attribute exists)

Retailer product **list** and **detail** include top-level `shelf_life_days`. If the product has a `shelf_life_days` attribute, the stored value is echoed. If the attribute is missing (this stack: Product has no shelf-life column), or the value is null, the payload is `null`. Zero stays zero. This is a field echo, not a new expiry model or write path.

POS `?no_page=true` is a hand-built dict and is unchanged. `ProductSearchSerializer` Meta is unchanged.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list / detail identity and inventory scalars | EXISTING |
| Optional `shelf_life_days` on list / detail | EXTEND |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| Product `shelf_life_days` column / expiry policy | Out of scope |

## API

| Method | Path | Who | `shelf_life_days` |
|--------|------|-----|-------------------|
| GET | `/api/products/` | Authenticated retailer | `getattr(product, 'shelf_life_days', None)` |
| GET | `/api/products/?no_page=true` | Authenticated retailer | omitted — POS views locked |
| GET | `/api/products/<id>/` | Authenticated retailer | same |
| GET | `/api/products/retailer/<id>/` | Public | same (shared list serializer) |
| GET | `/api/products/search/` | Authenticated retailer | omitted — search Meta locked |

Missing attribute → `null`. Null stays null. `0` stays `0`. Do not invent a default shelf life.

Write payloads may include `shelf_life_days`; it is ignored. The SKU is not changed.

Unauthenticated retailer list/detail → **401**. Customer / no retailer profile → **403**. Tenant B cannot read tenant A's product (absent / **404**).

`get_shelf_life_days` reads the product instance already being serialized. No extra product query.

## Not in this change

Search Meta, POS `products/views.py` row keys, GST/HSN rebuild, batch expiry policy (OE-136), inventory.adjust, pack write, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live `*.ordereasy.win`.
