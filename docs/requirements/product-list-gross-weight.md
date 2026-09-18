# Optional gross_weight on product list

- **Implementation:** EXTEND (optional echo of `Product.gross_weight` when the attribute exists)

Retailer product **list** may include top-level `gross_weight`. If the product instance already has a `gross_weight` attribute, the stored value is echoed via `to_representation` (not serializer Meta). If the attribute is missing (this stack: Product has no `gross_weight` column), the key is omitted. Null stays null. Do not invent `0`. This is a field echo, not a shipping-weight engine or a new catalog column.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list identity (`id` / `name` / `barcode`) | EXISTING |
| Optional `gross_weight` on `ProductListSerializer` when the attribute exists | EXTEND |
| `ProductListSerializer` / `ProductSearchSerializer` / `ProductDetailSerializer` Meta | EXISTING — do not add `gross_weight` |
| POS `?no_page=true` row dict | EXISTING — do not add `gross_weight` |
| `ProductDetailSerializer` payload | EXISTING — do not add `gross_weight` |
| Product `gross_weight` column / write path | Out of scope |

## API

| Method | Path | Who | `gross_weight` |
|--------|------|-----|----------------|
| GET | `/api/products/` | Authenticated retailer | Present only when `hasattr(product, 'gross_weight')` |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Same omit-if-missing via shared list serializer |

Other `ProductListSerializer` callers (featured / seasonal / similar catalog list routes) inherit the same optional key. POS `?no_page=true` is a hand-built dict and stays without `gross_weight`.

Missing attribute → key omitted. Null stays null. Do not coerce to `0`.

Unauthenticated retailer list → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

`to_representation` reads the already-loaded product row. The echo adds no extra product query.

## Not in this change

Model/migration for `gross_weight`, serializer Meta.fields, search Meta, POS `products/views.py` row keys, detail serializer, cart, returns, purchase invoice, customers, orders, inventory.adjust, pack write, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live `*.ordereasy.win`.
