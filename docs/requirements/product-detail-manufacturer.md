# Optional manufacturer on product detail

- **Implementation:** EXTEND (optional echo of `Product.manufacturer` when the attribute exists)
- **Related:** [search-pos-brand-name.md](search-pos-brand-name.md) (list/detail already expose `brand_name`)

Retailer and public **product detail** include top-level `manufacturer`. If the product has a `manufacturer` attribute, that attribute value is echoed when present. If the attribute is missing (this stack: Product has no manufacturer column), or the value is null, the payload is `null`. Empty string stays empty. This is a field echo, not a manufacturer model or catalog rebuild.

`manufacturer` is **not** added to `ProductDetailSerializer.Meta.fields` (or list/search Meta). Detail injects the key in `to_representation` via `getattr`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product detail identity (`name`, `brand`, `brand_name`) | EXISTING |
| Optional `manufacturer` on product detail | EXTEND |
| `ProductListSerializer` / `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `products/views.py` `?no_page=true` | EXISTING — do not change |
| Product `manufacturer` column | Out of scope |

## API

| Method | Path | Who | `manufacturer` |
|--------|------|-----|----------------|
| GET | `/api/products/<id>/` | Authenticated retailer | `getattr(product, 'manufacturer', None)` |
| GET | `/api/products/retailer/<retailer_id>/<id>/` | Public / customer | Same getter (shared detail serializer) |

Missing attribute → `null`. Null stays null. Empty stays empty. Do not invent a manufacturer.

Write payloads may include `manufacturer`; it is ignored. The SKU is not changed. Update/create write policy is unchanged.

Unauthenticated retailer detail → **401**. Customer on retailer detail → **403**. Tenant B cannot read tenant A's SKU (absent / **404**). Public detail stays AllowAny for that shop's active SKU.

The getter reads the product row already loaded for detail. No extra manufacturer query.

## Not in this change

Manufacturer model/column, list/search Meta, POS views, cart, returns, purchase invoice, ledger, inventory.adjust, timeline/OFD/khata/UPI/slots, pack write, FE, Jira Done, live `*.ordereasy.win`.
