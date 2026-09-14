# ProductBatch expiry and FIFO pick

- **Ticket:** [OE-136](https://vin8003.atlassian.net/browse/OE-136) · backlog `F-0030` · [snapshot](../tickets/OE-136.md)
- **Implementation:** EXTEND (`ProductBatch.expiry_date` + sale/pick on `Product.reduce_quantity`)
- **Depends on:** [inventory-adjust-permission.md](inventory-adjust-permission.md), [inventory-and-batches.md](../07-KEY-FLOWS/inventory-and-batches.md)

Batches can store an optional expiry date. At sale/pick, FIFO consumes the earliest **dated** eligible batch first. Expired lots cannot be sold. Existing batches with null expiry stay valid.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `ProductBatch` batch_number, prices, quantity | EXISTING |
| FIFO consume on `Product.reduce_quantity` when `batch` is omitted | EXISTING (was `created_at` oldest) |
| Optional `expiry_date` (`DateField` null=True) | EXTEND |
| FIFO = earliest non-null `expiry_date`, then `created_at`; **nulls last** | EXTEND |
| Default policy: forbid selling `expiry_date < today` | EXTEND (no org policy model) |
| Null-expiry batches remain saleable | EXISTING, locked |
| Expiry create/change on product update requires `inventory.adjust` | EXTEND |
| Cross-tenant product get/update still retailer-scoped | EXISTING, locked |
| `mfg_date`, LIFO/MRP engines, org FIFO flag, FE pickers, `StockMovement` | Out of scope |

## Sale / pick

POS `create_pos_order` and customer `place_order` already call `Product.reduce_quantity` (specific `batch_id` on POS, FIFO when omitted).

Eligible batch: `is_active`, and (`expiry_date` is null **or** `expiry_date >= local today`). Quantity must be `> 0` for the FIFO walk; `allow_negative` leftover may oversell a **saleable** batch only — never an expired one.

Sort: `expiry_date ASC NULLS LAST`, then `created_at ASC`.

`Product.quantity` still sums all **active** batches (expired qty can remain on the product total until written off — E16 / OE-141). `can_order_quantity` uses saleable qty so checkout cannot reserve expired-only stock.

## API

| Method | Path | Expiry change | Who |
|--------|------|---------------|-----|
| PUT/PATCH | `/api/products/<id>/update/` | `batches[].expiry_date` **differs** from stored, or a new batch is created **with a date** | `inventory.adjust` or **403** |
| PATCH | `/api/products/bulk-update/` | expiry keys are **not written** | ignored |

Echoing the current expiry (including null) does not require the perm. Cashiers can still save price/name. No new permission code.

## Not in this change

LIFO or MRP selection engines, org-level FIFO/expired policy flags, `mfg_date`, receiving/POS picker UI, `StockMovement` documents, reservation-hold redesign, E16 expiry reports, live `*.ordereasy.win`.
