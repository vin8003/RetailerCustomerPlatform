# Optional is_serialized on product list

- **Implementation:** EXTEND (optional echo of `Product.is_serialized` when the attribute exists)

Retailer product **list** includes top-level `is_serialized`. If the product has an `is_serialized` attribute, the stored value is echoed. If the attribute is missing (this stack: Product has no serialized-tracking column), or the value is null, the payload is `null`. False stays false. This is a field echo, not a serial-number / IMEI inventory model.

The list serializer does **not** add `is_serialized` to `Meta.fields` (that would require a model column). The key is injected in `to_representation` via `getattr`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list identity (`id` / `name` / `barcode`) | EXISTING |
| Optional `is_serialized` on `ProductListSerializer` | EXTEND |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `?no_page=true` row dict | EXISTING — do not add `is_serialized` |
| `ProductDetailSerializer` | EXISTING — do not add `is_serialized` |
| Product `is_serialized` column / serial ledger | Out of scope |

## API

| Method | Path | Who | `is_serialized` |
|--------|------|-----|-----------------|
| GET | `/api/products/` | Authenticated retailer | `getattr(product, 'is_serialized', None)` |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Additive via shared list serializer |

Missing attribute → `null`. Null stays null. False stays false. Do not invent True.

Unauthenticated retailer list → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

`product_is_serialized` reads the already-loaded product row. The echo adds no extra product query.

## Not in this change

Serial-number ledger, IMEI / serialized inventory writes, search Meta, POS `products/views.py` row keys, detail serializer, cart, returns, purchase invoice, customers, orders, inventory.adjust, pack write, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live production hosts.
