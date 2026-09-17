# Pack children on retailer parent SKU reads

- **Ticket:** [OE-191](https://vin8003.atlassian.net/browse/OE-191) · backlog `F-0019` (thin slice) · [snapshot](../tickets/OE-191.md)
- **Implementation:** EXTEND (reuse `Product.fractional_children` / `parent_bulk_product`)
- **Depends on:** [parent-child-pack-skus.md](parent-child-pack-skus.md), [saleable-quantity-reads.md](saleable-quantity-reads.md)

Retailer **GET** of a parent SKU includes active pack children. Each child is `id`, `name`, `conversion_factor`, and `saleable_quantity` from the existing helper (`parent.saleable_quantity() / conversion_factor`). Non-parent SKUs return `[]`.

This is not a kit/BOM. There is no assemble write and no explode-at-sale.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.fractional_children` related_name on `parent_bulk_product` | EXISTING |
| Parent flags `is_parent_bulk` / `parent_bulk_product` / `conversion_factor` on list/detail | EXISTING |
| `Product.saleable_quantity()` (OE-132 / OE-136) | EXISTING |
| `fractional_children` array on retailer list + detail | EXTEND |
| Kit/BOM tables, break-bulk write, explode-at-sale | Out of scope |

## API

| Method | Path | Who | `fractional_children` |
|--------|------|-----|-----------------------|
| GET | `/api/products/<id>/` | Authenticated retailer | Active children when `is_parent_bulk`; else `[]` |
| GET | `/api/products/` | Authenticated retailer | Same (paginated list) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Omitted (POS path has no pack flags) |
| GET | `/api/products/search/` | Authenticated retailer | Omitted (search has no pack flags) |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Omitted |

Child rows are same-shop and `is_active=True` only. List/detail prefetch `fractional_children` so the helper does not query per parent.

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's parent (**404** on detail; absent from list).

## Not in this change

Full F-0019 kit/BOM tables, OE-159 break-bulk write, kit explode-at-sale, OE-102, #103, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
