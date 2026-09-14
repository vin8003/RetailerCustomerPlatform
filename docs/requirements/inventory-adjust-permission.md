# Hand-set on-hand requires `inventory.adjust`

- **Ticket:** [OE-127](https://vin8003.atlassian.net/browse/OE-127) · backlog `F-0028` · [snapshot](../tickets/OE-127.md)
- **Implementation:** EXTEND (permission catalog + product update/bulk gate)
- **Depends on:** [shop-staff-roles.md](shop-staff-roles.md) (`inventory.adjust` in the versioned catalog)

Cashiers must not type a new on-hand number on product update or bulk update. Shop **owners** (implicit full catalog) and anyone granted `inventory.adjust` still can. Sale and purchase continue to change quantity through their existing dual-write paths (`Product.quantity` + `ProductInventoryLog`).

There is no `StockMovement` ledger cutover in this slice (OE-263 / OE-185 stay backlog).

## API

| Method | Path | When the body sets on-hand | Who |
|--------|------|----------------------------|-----|
| PUT/PATCH | `/api/products/<id>/update/` | `quantity` or `batches[].quantity` | `inventory.adjust` or **403** |
| PATCH | `/api/products/bulk-update/` | any `items[].quantity` | `inventory.adjust` or **403** (nothing applied) |

Price, name, and other non-qty fields are unchanged: they do not require `inventory.adjust`.

Retailer tenancy is unchanged: products are still loaded as `id` + the caller's `RetailerProfile`. Cross-tenant ids do not update the other shop's stock.

## Roles

- Catalog version includes `inventory.adjust`.
- System **Admin** bootstrap includes every catalog code (this one too).
- System **Cashier** bootstrap stays empty — no inventory permissions.
- There is no separate manager system role. Assign `inventory.adjust` on a named role when a non-owner should hand-set stock.

## Admin

`ProductInventoryLog` is read-only in Django admin (no add / change / delete).
