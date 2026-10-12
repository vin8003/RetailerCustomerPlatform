# Customer profile credit balances

- **Ticket:** [KAN-70](https://vin8003.atlassian.net/browse/KAN-70) · [snapshot](../tickets/KAN-70.md)
- **Apps:** `customer_ordereasy_njs` (live https://customer.ordereasy.win) · `RetailerCustomerPlatform`

The customer profile shows **retailer-wise credit (khata) balances**, not the order-detail screen.

## Rules

- Each `RetailerCustomerMapping` for the logged-in customer is one row (shop name, outstanding, credit limit, remaining).
- **Show the row even when `credit_limit` is 0.** Outstanding (`current_balance`) is still the amount owed.
- Remaining credit is `credit_limit - current_balance` and may be negative when they owe more than the limit.
- Do not hide another retailer’s balances from this customer, and do not leak another customer’s mappings.
- Order detail in the customer app must **not** show the Credit / Khata block added in KAN-61 (it only appeared when limit > 0). Payment mode on the order still shows as credit/khata.

## API contract

```
GET /api/customer/credit/all/
```

Authenticated customers only. Retailer users receive 403. Response is a JSON list:

| Field | Type | Notes |
|-------|------|--------|
| `retailer_id` | number | |
| `retailer_name` | string | `RetailerProfile.shop_name` |
| `credit_limit` | number | Always present, including `0` |
| `current_balance` | number | Outstanding owed, including `0` |
| `remaining_credit` | number | `credit_limit - current_balance` |

## Related

- [credit-khata.md](../07-KEY-FLOWS/credit-khata.md) — mapping + ledger
- [credit-remaining-balance.md](credit-remaining-balance.md) — KAN-61 bill remaining (superseded for customer order detail by this ticket)
