# Khata credit limit and lock

- **Ticket:** [OE-143](https://vin8003.atlassian.net/browse/OE-143) · backlog `F-0052` · [snapshot](../tickets/OE-143.md)
- **Implementation:** EXTEND (`RetailerCustomerMapping` due days + server-side lock on POS credit finalize)
- **Depends on:** [credit-khata.md](../07-KEY-FLOWS/credit-khata.md), [shop-staff-roles.md](shop-staff-roles.md)

Credit sales lock when the running khata balance would exceed `credit_limit`, or when outstanding has been open longer than `credit_due_days`. Override is an explicit POS flag plus `orders.update`. Customers can still settle while locked. No bill-wise ledger (F-0064 / OE-129).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `RetailerCustomerMapping.credit_limit` + `current_balance` | EXISTING |
| `CustomerLedger` SALE / PAYMENT / RETURN / ADJUSTMENT | EXISTING |
| POS `create_pos_order` credit / split tender | EXISTING |
| App `place_order` credit tender | MISSING (app checkout stays cash / UPI / cash_pickup) |
| `credit_due_days` (null = no due-days lock) | EXTEND |
| `outstanding_since` (running-balance clock, not bill-wise) | EXTEND |
| Server-side lock on POS credit finalize | EXTEND (limit was PARTIAL; due-days was MISSING) |
| Explicit `credit_override` + `orders.update` + `OrgAuditLog` | EXTEND |
| `record_customer_payment` while locked | EXISTING, locked (must stay allowed) |
| Unauthorized mutate of limit / due days | EXISTING 403 for non-retailer |
| Cross-tenant mapping mutate | EXISTING retailer-scoped 404 deny |
| Bill-wise allocation, FE lock badges, SupplierLedger rebuild | Out of scope |

## Lock rules

Evaluated **before** the POS `Order` row is created, only when `credit_amount > 0` and a customer is attached.

- `credit_limit == 0` → no limit lock.
- `credit_due_days is null` → no due-days lock.
- Limit: `current_balance + this credit_amount > credit_limit`.
- Due days: `current_balance > 0` and `outstanding_since` is set and calendar days elapsed `>= credit_due_days`.
- `outstanding_since` is set when running balance becomes positive and cleared when it returns to `<= 0`. It is not per-invoice aging.

Without `credit_override`, a lock is **400** and no order is written. With `credit_override` and without `orders.update` (owner is implicit admin), **403** and unchanged. With override + `orders.update`, the sale proceeds and an append-only `OrgAuditLog` row (`object_type=credit_override`, `action=grant`) is written.

Cash / UPI POS and `POST /api/customers/retailer/payment/record/` stay allowed while locked.

## API

| Method | Path | Behavior |
|--------|------|----------|
| POST | `/api/products/erp/pos-checkout/` | Credit finalize evaluates lock. Optional `credit_override`. |
| PATCH | `/api/customers/retailer/credit-limit/update/<customer_id>/` | Owner/retailer of that shop may set `credit_limit` and/or `credit_due_days`. Non-retailer **403**. Other shop **404**. |
| POST | `/api/customers/retailer/payment/record/` | Settle outstanding; not gated by lock. |

## Not in this change

Bill-wise khata (OE-129), FE POS picker lock badges, app-checkout credit tender, SupplierLedger, live `*.ordereasy.win`.
