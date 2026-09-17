# ProductBatch expiry and FIFO pick

- **Ticket:** [OE-136](https://vin8003.atlassian.net/browse/OE-136) · backlog `F-0030` · [snapshot](../tickets/OE-136.md); POS `no_page` echo [OE-144](https://vin8003.atlassian.net/browse/OE-144) · [snapshot](../tickets/OE-144.md)
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
| POS `no_page` active batch rows include `expiry_date` (null OK) | EXTEND (OE-144; same as `ProductBatchSerializer`) |
| Cross-tenant product get/update still retailer-scoped | EXISTING, locked |
| `mfg_date`, LIFO/MRP engines, org FIFO flag, FE pickers, `StockMovement` | Out of scope |

## Sale / pick

POS `create_pos_order` and customer `place_order` already call `Product.reduce_quantity` (specific `batch_id` on POS, FIFO when omitted).

Eligible batch: `is_active`, and (`expiry_date` is null **or** `expiry_date >= timezone.localdate()` — Django `TIME_ZONE`, currently UTC). Quantity must be `> 0` for the FIFO walk; `allow_negative` leftover may oversell a **saleable** batch only — never an expired one.

Sort: `expiry_date ASC NULLS LAST`, then `created_at ASC`.

`Product.quantity` still sums all **active** batches (expired qty remains on the product total until written off — [OE-141](damage-expiry-write-off.md)). `Product.saleable_quantity()` / `can_order_quantity` exclude expired lots. Customer `place_order` and cart stock checks use saleable qty; a failed `reduce_quantity` aborts the order. Purchase returns pass `forbid_expired=False` so expired lots can still be sent back to the supplier. Retailer/POS product **reads** expose that helper as `saleable_quantity` next to gross `quantity` — [saleable-quantity-reads.md](saleable-quantity-reads.md) (OE-132). POS `GET /api/products/?no_page=true` active batch rows also echo `expiry_date` (null OK), matching `ProductBatchSerializer`. That read does not change sale/pick policy.

## API

| Method | Path | Expiry change | Who |
|--------|------|---------------|-----|
| PUT/PATCH | `/api/products/<id>/update/` | `batches[].expiry_date` **differs** from stored, or a new batch is created **with a date** | `inventory.adjust` or **403** |
| PATCH | `/api/products/bulk-update/` | expiry keys are **not written** | ignored |

Echoing the current expiry (including null) does not require the perm. Cashiers can still save price/name. No new permission code.

## Not in this change

LIFO or MRP selection engines, org-level FIFO/expired policy flags, `mfg_date`, receiving/POS picker UI, `StockMovement` documents, reservation-hold redesign, full E16 MIS. Shop expiry **list** read is [expiry-batch-list.md](expiry-batch-list.md) (OE-210). Live `*.ordereasy.win`.
