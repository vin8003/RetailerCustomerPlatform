# Hand-set on-hand requires `inventory.adjust`

- **Ticket:** [OE-127](https://vin8003.atlassian.net/browse/OE-127) · backlog `F-0028` · [snapshot](../tickets/OE-127.md)
- **Implementation:** EXTEND (permission catalog + product update/bulk gate)
- **Depends on:** [shop-staff-roles.md](shop-staff-roles.md) (`inventory.adjust` in the versioned catalog)

Cashiers must not type a **new** on-hand number on product update or bulk update. Echoing the current quantity (typical full-object product save) does **not** require the perm. Shop **owners** (implicit full catalog) and anyone granted `inventory.adjust` can still change on-hand. Sale and purchase continue to change quantity through their existing dual-write paths (`Product.quantity` + `ProductInventoryLog`).

The same permission gates **parent-child pack link** mutations (`conversion_factor`, `parent_bulk_product`, `is_parent_bulk`) on product create and update (OE-103). Echoing the current pack-link values does not require the perm. It also gates **batch expiry** create/change on product update (`batches[].expiry_date`, OE-136). Echoing the current expiry (including null) does not require the perm. Bulk does not write expiry. `create_product` quantity and Excel/CSV upload stay ungated for on-hand (OE-127 next slice). There is no `StockMovement` ledger cutover (OE-263 / OE-185 stay backlog).

## API

| Method | Path | When the body sets on-hand | Who |
|--------|------|----------------------------|-----|
| PUT/PATCH | `/api/products/<id>/update/` | `quantity` or `batches[].quantity` **differs** from stored | `inventory.adjust` or **403** |
| PUT/PATCH | `/api/products/<id>/update/` | pack-link fields **differ** from stored (`conversion_factor`, `parent_bulk_product`, `is_parent_bulk`) | `inventory.adjust` or **403** |
| PUT/PATCH | `/api/products/<id>/update/` | `batches[].expiry_date` **differs** from stored, or a new batch is created with a date | `inventory.adjust` or **403** |
| POST | `/api/products/create/` | pack-link fields set away from defaults | `inventory.adjust` or **403** |
| PATCH | `/api/products/bulk-update/` | any `items[].quantity` **differs** from stored after the same `int()` write as apply | `inventory.adjust` or **403** (nothing applied) |

Bulk compare uses the same `int()` normalization as the write (echo `10.750` against stored `10.75` is a change — write would truncate to `10`). That compare runs **after** `select_for_update` so a concurrent sale cannot sneak a stale echo write.

Product update writes `Decimal` via the serializer and compares `Decimal` after the row lock — fractional echo does not truncate.

Price, name, and other non-qty / non-pack-link / non-expiry fields are unchanged: they do not require `inventory.adjust`. Pack-link and expiry keys on bulk update are ignored (bulk does not write them).

Retailer tenancy is unchanged: products are still loaded as `id` + the caller's `RetailerProfile`. Cross-tenant ids do not update the other shop's stock.

## Roles

- Catalog version includes `inventory.adjust`.
- System **Admin** bootstrap includes every catalog code (this one too).
- System **Cashier** bootstrap stays empty — no inventory permissions.
- There is no separate manager system role. Assign `inventory.adjust` on a named role when a non-owner should hand-set stock.

## Admin

`ProductInventoryLog` is read-only in Django admin (no add / change / delete).
