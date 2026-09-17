# Parent-child pack SKUs

- **Ticket:** [OE-103](https://vin8003.atlassian.net/browse/OE-103) · backlog `F-0021` · [snapshot](../tickets/OE-103.md)
- **Implementation:** EXTEND (reuse `Product.is_parent_bulk`, `parent_bulk_product`, `conversion_factor`)
- **Depends on:** [inventory-adjust-permission.md](inventory-adjust-permission.md), [inventory-and-batches.md](../07-KEY-FLOWS/inventory-and-batches.md)

A child pack (piece, 5kg bag) sells against the parent/base SKU (case, 50kg bag). Parent `Product.quantity` is the inventory source of truth. Child quantity is derived: `parent.quantity / conversion_factor`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Fields `is_parent_bulk`, `parent_bulk_product`, `conversion_factor` (KAN-13) | EXISTING |
| Child `reduce_quantity` / `increase_quantity` convert by factor onto the parent | EXISTING |
| POS `create_pos_order` and customer `place_order` call `reduce_quantity` | EXISTING |
| Same-retailer parent pointer on create/update serializers | EXISTING |
| `conversion_factor` cannot be zero (`MinValueValidator(0.0001)` + serializer) | EXISTING, hardened |
| Self / loop `parent_bulk_product` rejected | EXTEND (simple reject) |
| Pack-link mutations require `inventory.adjust` (or owner) | EXTEND |
| Matrix/kit UI, second catalog/pricing engine, `StockMovement` cutover | Out of scope |

## Sale

Selling `N` child units deducts `N * conversion_factor` from the parent (factor must be `> 0`). Parent sale still deducts parent units and re-syncs children. Child batch arguments are not passed through to the parent (FIFO on the parent).

## API

| Method | Path | Pack-link change | Who |
|--------|------|------------------|-----|
| POST | `/api/products/create/` | `conversion_factor` / `parent_bulk_product` / `is_parent_bulk=true` | `inventory.adjust` or **403** |
| PUT/PATCH | `/api/products/<id>/update/` | those fields **differ** from stored | `inventory.adjust` or **403** |
| PATCH | `/api/products/bulk-update/` | pack-link keys are **not written** | ignored |

`conversion_factor == 0` (and any non-positive value) is **400**. Echoing the current factor on a full product save does not require the perm. Cross-tenant product id is **404**; pointing `parent_bulk_product` at another shop's SKU is **400**.

Retailer GET of a parent SKU also returns active `fractional_children` — see [pack-children-reads.md](pack-children-reads.md). Retailer search and POS `no_page` echo the same pack identity scalars already on list/detail (`is_parent_bulk`, `parent_bulk_product` id, `conversion_factor`).

## Cycle policy

Simple reject: a product cannot be its own parent, and a parent pointer chain cannot loop. No auto-break.

## Not in this change

Matrix/kit UI, a second catalog or pricing engine, `StockMovement` ledger, FE rebuild, live `*.ordereasy.win`.
