# Damage, expiry, and spoilage write-off

- **Ticket:** [OE-141](https://vin8003.atlassian.net/browse/OE-141) · backlog `F-0032` · [snapshot](../tickets/OE-141.md)
- **Implementation:** EXTEND (`Product.quantity` + `ProductBatch` + `ProductInventoryLog`)
- **Depends on:** [inventory-adjust-permission.md](inventory-adjust-permission.md), [product-batch-expiry.md](product-batch-expiry.md), [inventory-and-batches.md](../07-KEY-FLOWS/inventory-and-batches.md)

Record shrinkage against on-hand with a reason code. This is not a second stock engine and does not introduce `StockMovement`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.quantity` / `ProductBatch.quantity` as on-hand | EXISTING |
| `ProductInventoryLog` (`damaged` / `expired` types, free-text `reason`) | EXISTING |
| `spoiled` log type | EXTEND |
| Write-off reason codes `damage` / `expiry` / `spoilage` stored on `reason` | EXTEND |
| `POST /api/products/<id>/write-off/` decreases on-hand under row lock | EXTEND |
| Expiry write-off requires `ProductBatch.is_expired()` | EXTEND |
| Permission `inventory.adjust` | EXISTING (no new code) |
| Ledger `?reason=` filter (API list; no report UI) | EXTEND |
| Cross-tenant product get/update still retailer-scoped | EXISTING, locked |
| `StockMovement`, FE / WMS, ATP, second qty cache | Out of scope |

## Reason codes

| Request `reason` | `ProductInventoryLog.log_type` | Extra rule |
|------------------|--------------------------------|------------|
| `damage` | `damaged` | Batch required when `has_batches` |
| `spoilage` | `spoiled` | Batch required when `has_batches` |
| `expiry` | `expired` | Batch required; `expiry_date < today` (null expiry is not expired) |

Quantity is a positive `Decimal`. It cannot exceed the target batch (or product) on-hand. Inactive batches and fractional children are rejected — write off an active lot, or the parent bulk product.

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| POST | `/api/products/<id>/write-off/` | `inventory.adjust` or **403** | Body: `quantity`, `reason`, optional `batch_id`. Cross-tenant id is **404**. |
| GET | `/api/products/erp/inventory-ledger/` | Shop retailer JWT | `product_id` and/or `reason`. `reason` exact-match. Other shop's `product_id` is **404**. Rows echo list identity (`product_id` / `product_name` / `barcode`); see [inventory-ledger-product-identity.md](inventory-ledger-product-identity.md). Optional `expiry_date` only if the log field exists ([inventory-ledger-expiry.md](inventory-ledger-expiry.md)). |

Write-off response includes `reason`, `log_type`, `quantity_change`, `previous_quantity`, `new_quantity`, `batch_id`.

## Not in this change

`StockMovement` ledger cutover (OE-263 / OE-185 stay backlog), separate document types per reason, retailer write-off UI / WMS mobile, E16 expiry report screens, live `*.ordereasy.win`.
