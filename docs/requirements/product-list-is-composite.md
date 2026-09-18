# Optional is_composite on product list

- **Implementation:** EXTEND (optional echo of `Product.is_composite` when the attribute exists)
- **Related:** [parent-child-pack-skus.md](parent-child-pack-skus.md) (OE-103), [pack-children-reads.md](pack-children-reads.md) (OE-191 / OE-283 / OE-285)

Retailer and public **product list** include top-level `is_composite`. If the product has an `is_composite` attribute, the stored value is echoed. If the attribute is missing (this stack: Product has no `is_composite` column), or the value is null, the payload is `null`. `false` stays `false`. This is a field echo, not a kit/BOM model or explode-at-sale (F-0019 / OE-159 stay later).

`is_composite` is **not** added to `ProductListSerializer.Meta.fields` (or search/detail Meta). List injects the key in `to_representation` via `getattr`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list identity (`id` / `name` / `barcode`) | EXISTING |
| Pack identity (`is_parent_bulk`, `parent_bulk_product`, `conversion_factor`) | EXISTING |
| Optional `is_composite` on product list | EXTEND |
| `ProductSearchSerializer` / `ProductDetailSerializer` Meta | EXISTING — do not change |
| POS `products/views.py` `?no_page=true` | EXISTING — do not change |
| Product `is_composite` column / kit BOM | Out of scope |

## API

| Method | Path | Who | `is_composite` |
|--------|------|-----|----------------|
| GET | `/api/products/` | Authenticated retailer | `getattr(product, 'is_composite', None)` |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Additive via shared list serializer |

Missing attribute → `null`. Null stays null. `false` stays `false`. Do not invent a composite flag.

Write payloads may include `is_composite`; it is ignored. The SKU is not changed. Update/create write policy is unchanged.

Unauthenticated retailer list → **401**. Customer on retailer list → **403**. Tenant B cannot read tenant A's SKU.

The getter reads the product row already loaded for list. No extra composite query.

## Not in this change

Kit/BOM invent, explode-at-sale, search Meta, POS views, detail serializer, cart, returns, purchase invoice, ledger, inventory.adjust, timeline/OFD/khata/UPI/slots, pack write, FE, Jira Done, live `*.ordereasy.win`.
