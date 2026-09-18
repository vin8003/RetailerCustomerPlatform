# Optional track_batch on product list

- **Implementation:** EXTEND (optional echo of `Product.track_batch` when the attribute exists)

Retailer product **list** includes top-level `track_batch`. If the product has a `track_batch` attribute, the stored bool is echoed. If the attribute is missing (this stack: Product has no `track_batch` column), or the value is null, the payload is `null`. False stays false. Do not invent a bool from `has_batches`. This is a field echo, not batch write, FIFO, or a `has_batches` rename.

The key is injected in `to_representation`. **Do not add `track_batch` to `Meta.fields`** (`ProductListSerializer`, search, or detail).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list identity (`id` / `name` / `barcode` / `has_batches`) | EXISTING |
| Optional `track_batch` on `ProductListSerializer` (`to_representation`) | EXTEND |
| `ProductListSerializer` / `ProductSearchSerializer` / `ProductDetailSerializer` Meta | EXISTING — do not change |
| POS `?no_page=true` row dict | EXISTING — do not add `track_batch` |
| Product `track_batch` column / batch write | Out of scope |

## API

| Method | Path | Who | `track_batch` |
|--------|------|-----|----------------|
| GET | `/api/products/` | Authenticated retailer | `getattr` + bool when the attribute exists; else `null` |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Additive via shared list serializer |

Missing attribute → `null`. Null stays null. False stays false. Do not invent from `has_batches`.

Unauthenticated retailer list → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

`product_track_batch` reads the already-loaded product row. The echo adds no extra product query.

## Not in this change

Search Meta, POS `products/views.py` row keys, detail serializer, `has_batches` rename, batch write / FIFO / expiry, cart, returns, purchase invoice, customers, orders, inventory.adjust, pack write, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live `*.ordereasy.win`.
