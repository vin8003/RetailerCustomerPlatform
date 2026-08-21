# Credit & Khata System

## Overview

The platform supports two related concepts:

- **Customer Credit** (what the customer owes the retailer)
- **Supplier Khata** (what the retailer owes suppliers)

## Customer Credit

### RetailerCustomerMapping

Each retailer-customer relationship tracks:

- `credit_limit` – maximum amount the customer is allowed to owe
- `current_balance` – current outstanding amount

### Ledger Entries

All movements are recorded in `CustomerLedger`:

| Type | Effect on Balance |
|------|-------------------|
| SALE (on credit) | Increases balance |
| PAYMENT | Decreases balance |
| RETURN | Decreases balance |
| ADJUSTMENT | Increases or decreases as needed |

### Flow

```mermaid
flowchart LR
    Map[RetailerCustomerMapping<br/>credit_limit + current_balance]
    Sale[Order with payment_mode = credit] --> L1[CustomerLedger: SALE]
    Pay[Customer payment] --> L2[CustomerLedger: PAYMENT]
    Ret[Return / Adjustment] --> L3[CustomerLedger: RETURN / ADJUSTMENT]
    L1 & L2 & L3 --> Map
    Map -->|balance > credit_limit| Block[Warn or block further credit]
```

## Supplier Khata

- `PurchaseInvoice` increases the amount owed to the supplier.
- Payments to the supplier decrease the balance.
- Tracked via `SupplierLedger`.

## Key Rules

- Balance is always updated in real time.
- Credit limit can be used to block or warn on further credit sales.
- Full history is available through the ledger entries.
