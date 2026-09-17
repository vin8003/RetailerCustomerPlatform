# Pack children on retailer parent SKU reads

- **Ticket:** [OE-191](https://vin8003.atlassian.net/browse/OE-191) · [OE-283](https://vin8003.atlassian.net/browse/OE-283) · [OE-285](https://vin8003.atlassian.net/browse/OE-285) · backlog `F-0019` (thin slice) · [OE-191 snapshot](../tickets/OE-191.md) · [OE-283 snapshot](../tickets/OE-283.md) · [OE-285 snapshot](../tickets/OE-285.md)
- **Implementation:** EXTEND (reuse `Product.fractional_children` / `parent_bulk_product`)
- **Depends on:** [parent-child-pack-skus.md](parent-child-pack-skus.md), [saleable-quantity-reads.md](saleable-quantity-reads.md)

Retailer **GET** of a parent SKU includes active pack children. Each child is `id`, `name`, `conversion_factor`, and `saleable_quantity` from the existing helper (`parent.saleable_quantity() / conversion_factor`). Non-parent SKUs return `[]`.

This is not a kit/BOM. There is no assemble write and no explode-at-sale.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.fractional_children` related_name on `parent_bulk_product` | EXISTING |
| Parent flags `is_parent_bulk` / `parent_bulk_product` / `conversion_factor` on list/detail | EXISTING |
| Same pack identity scalars on retailer search + POS `no_page` | EXTEND (OE-285) |
| `Product.saleable_quantity()` (OE-132 / OE-136) | EXISTING |
| `fractional_children` array on retailer list + detail | EXTEND (OE-191) |
| `fractional_children` on retailer search + POS `no_page` | EXTEND (OE-283) |
| Kit/BOM tables, break-bulk write, explode-at-sale | Out of scope |

## API

| Method | Path | Who | `fractional_children` |
|--------|------|-----|-----------------------|
| GET | `/api/products/<id>/` | Authenticated retailer | Active children when `is_parent_bulk`; else `[]` |
| GET | `/api/products/` | Authenticated retailer | Same (paginated list) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same (POS catalog) |
| GET | `/api/products/search/` | Authenticated retailer | Same |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Omitted |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Omitted |

Child rows are same-shop and `is_active=True` only. List/detail/search prefetch `fractional_children` so the helper does not query per parent. POS `no_page` uses the same prefetch on the hand-built payload.

Retailer search and POS `no_page` also echo pack identity scalars already on list/detail: `is_parent_bulk`, `parent_bulk_product` (FK id), `conversion_factor`. Non-pack SKUs keep `false` / `null` / `null`. Those reads `select_related('parent_bulk_product')` so pack identity and the existing saleable-qty cache do not fetch the parent per child. Public list/detail stay unchanged; public search uses the same search serializer so the three model fields appear there too.

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's parent (**404** on detail; absent from list/search/POS).

## Not in this change

Full F-0019 kit/BOM tables, OE-159 break-bulk write, kit explode-at-sale, OE-102, #103, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
