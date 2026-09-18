# Optional color on product list

- **Implementation:** EXTEND (optional echo of `Product.color` when the attribute exists)

Retailer product **list** includes top-level `color`. If the product has a `color` attribute, the stored value is echoed. If the attribute is missing (this stack: Product has no color column), or the value is null, the payload is `null`. Empty string stays empty. This is a field echo, not a size/color matrix or variant SKU generator (OE-192 / F-0018 stay later).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list identity (`id` / `name` / `barcode`) | EXISTING |
| Optional `color` on `ProductListSerializer` | EXTEND |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `?no_page=true` row dict | EXISTING — do not add `color` |
| `ProductDetailSerializer` | EXISTING — do not add `color` |
| Product `color` column / size-color matrix | Out of scope |

## API

| Method | Path | Who | `color` |
|--------|------|-----|---------|
| GET | `/api/products/` | Authenticated retailer | `getattr(product, 'color', None)` |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Additive via shared list serializer |

Missing attribute → `null`. Null stays null. Empty stays empty. Do not invent a color.

Unauthenticated retailer list → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

`get_color` reads the already-loaded product row. The echo adds no extra product query.

## Not in this change

Size/color matrix, variant SKU invent, search Meta, POS `products/views.py` row keys, detail serializer, cart, returns, purchase invoice, customers, orders, inventory.adjust, pack write, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live production hosts.
