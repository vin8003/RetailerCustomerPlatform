# Credit & Khata System

## Overview

The platform supports two related concepts:

- **Customer Credit** (what the customer owes the retailer)
- **Supplier Khata** (what the retailer owes suppliers)

## Customer Credit

### RetailerCustomerMapping

Each retailer-customer relationship tracks:

- `credit_limit` – maximum amount the customer is allowed to owe (`0` = unset, no limit lock)
- `current_balance` – current outstanding amount
- `credit_due_days` – optional days after outstanding opens before new credit sales lock (`null` = no due-days lock)
- `outstanding_since` – when running balance last became positive (cleared at zero; not bill-wise)

Server-side lock on POS credit finalize (OE-143 / F-0052): block if this credit amount would exceed `credit_limit`, or if outstanding is older than `credit_due_days`. Explicit `credit_override` requires `orders.update` and writes `OrgAuditLog`. Payments stay allowed while locked. See [khata-credit-lock.md](../requirements/khata-credit-lock.md).

### Ledger Entries

All movements are recorded in `CustomerLedger`:

| Type | Effect on Balance |
|------|-------------------|
| SALE (on credit) | Increases balance |
| PAYMENT | Decreases balance |
| RETURN | Decreases balance |
| ADJUSTMENT | Increases or decreases as needed |

### Flow

![Credit and Khata System](../visuals/credit-khata-system.jpg)

*Illustrative diagram: Left side shows Customer Credit (Retailer–Customer mapping + ledger entries that increase/decrease balance). Right side shows Supplier Khata (Purchase Invoice increases what you owe; Payment to supplier decreases it).*

```mermaid
flowchart LR
    Map[RetailerCustomerMapping<br/>credit_limit + current_balance<br/>credit_due_days + outstanding_since]
    Sale[POS credit finalize] --> Eval[Limit or overdue lock]
    Eval -->|blocked| Block[400 unless credit_override + orders.update]
    Eval -->|allowed or override| L1[CustomerLedger: SALE]
    Pay[Customer payment] --> L2[CustomerLedger: PAYMENT]
    Ret[Return / Adjustment] --> L3[CustomerLedger: RETURN / ADJUSTMENT]
    L1 & L2 & L3 --> Map
```

## Supplier Khata

- `PurchaseInvoice` increases the amount owed to the supplier.
- Payments to the supplier decrease the balance.
- Tracked via `SupplierLedger`.

## Key Rules

- Balance is always updated in real time.
- Credit limit and optional due days lock further **credit** sales on POS finalize; cash/UPI and khata payments are not locked.
- Override of a lock is audited (`OrgAuditLog`, `orders.update`).
- Full history is available through the ledger entries.
- Customer-facing credit bills must show remaining balance on the bill itself ([credit-remaining-balance.md](../requirements/credit-remaining-balance.md), KAN-61).
