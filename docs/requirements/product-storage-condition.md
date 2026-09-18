# Optional storage_condition on product list/detail

- **Implementation:** EXTEND (optional echo of `Product.storage_condition` when the attribute exists)
- **Related:** [inventory-ledger-product-identity.md](inventory-ledger-product-identity.md) (OE-315 stack base)

Retailer and public **product list** and **product detail** may include top-level `storage_condition`. If the product has a `storage_condition` attribute, that string is echoed as-is. If the attribute or column is absent (this stack: Product has no `storage_condition` field), the key is **omitted**. This is a field echo, not a storage-policy model or catalog rebuild.

Do **not** invent `storage_condition` from `description`, `notes`, or `care_instructions`.

`storage_condition` is **not** added to `ProductListSerializer.Meta.fields` or `ProductDetailSerializer.Meta.fields` (or search/create/update Meta). List/detail inject the key in `to_representation` only when `hasattr(product, 'storage_condition')`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list/detail identity (`name`, `description`) | EXISTING |
| Optional `storage_condition` on product list/detail | EXTEND |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `products/views.py` `?no_page=true` | EXISTING — do not change |
| Product `storage_condition` column | Out of scope |

## API

| Method | Path | Who | `storage_condition` |
|--------|------|-----|---------------------|
| GET | `/api/products/` | Authenticated retailer | Echo attribute when present; omit key when absent |
| GET | `/api/products/<id>/` | Authenticated retailer | Same mixin |
| GET | `/api/products/retailer/<retailer_id>/` | Public / customer | Shared list serializer |
| GET | `/api/products/retailer/<retailer_id>/<id>/` | Public / customer | Shared detail serializer |

Missing attribute → key omitted. Present null stays null. Empty string stays empty. Do not invent a storage condition.

Write payloads may include `storage_condition`; it is ignored. The SKU is not changed. Update/create write policy is unchanged.

Unauthenticated retailer list/detail → **401**. Customer on retailer list/detail → **403**. Tenant B cannot read tenant A's SKU (absent / **404**). Public list/detail stays AllowAny for that shop's active SKU.

The getter reads the product row already loaded for list/detail. No extra storage-condition query.

## Not in this change

`storage_condition` model/column, search Meta, POS views, cart, returns, purchase invoice, ledger, inventory.adjust, timeline/OFD/khata/UPI/slots, pack write, FE, Jira Done, live `*.ordereasy.win`.
