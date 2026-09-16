# Block negative stock

- **Ticket:** [OE-146](https://vin8003.atlassian.net/browse/OE-146) · backlog `F-0033` · [snapshot](../tickets/OE-146.md)
- **Implementation:** EXTEND (`Product.reduce_quantity(allow_negative=…)` on existing sale deducts)
- **Depends on:** [inventory-and-batches.md](../07-KEY-FLOWS/inventory-and-batches.md), [product-batch-expiry.md](product-batch-expiry.md)

Sale deducts cannot take on-hand below zero unless the caller already passes the existing `allow_negative=True` flag. There is no org/location policy model in this slice.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.reduce_quantity(..., allow_negative=False)` | EXISTING |
| POS `create_pos_order` hardcoded `allow_negative=True` | EXTEND — default block |
| POS body `allow_negative: true` (JSON boolean only) | EXTEND — existing flag wired through |
| Customer `place_order` / order-modify deduct | EXISTING, now explicit `allow_negative=False` |
| Purchase return deduct `allow_negative=True` | EXISTING override |
| Org/location policy, correction tasks, FE settings | Out of scope |

## Sale paths

| Path | Default | Override |
|------|---------|----------|
| POS `POST /api/products/erp/pos-checkout/` | Block | Body `allow_negative` is exactly JSON `true` |
| Customer `place_order` | Block | None on the HTTP body |
| Retailer order-modify extra qty | Block | None |
| Purchase return to supplier | Allow | Already passes `allow_negative=True` |

A blocked sale returns **400** (`Not enough saleable stock for …`). The product row and order create stay unchanged (`transaction.atomic`). Selling the last unit down to **zero** is allowed.

`place_order`, order-modify, and POS `create_pos_order` lock sold SKUs (and pack parents) with one `Product.lock_for_sale` in pk order before `reduce_quantity`. `ProductBatch` is still `select_for_update` when the caller has a batch. Pack-child sales must not lock child-then-parent ad hoc (AB-BA with the shared ASC protocol).

`allow_negative` leftover on batched products still cannot consume an expired lot (OE-136).

## Not in this change

Per-org or per-location policy UI, audited correction tasks, FE stock settings, invent notify, a new inventory service layer, `StockMovement` SoT, live `*.ordereasy.win`.
