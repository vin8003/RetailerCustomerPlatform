# Remaining credit on customer bill

- **Ticket:** [KAN-61](https://vin8003.atlassian.net/browse/KAN-61) · [snapshot](../tickets/KAN-61.md)
- **App:** `customer_ordereasy_njs` · live https://customer.ordereasy.win

A credit bill must show **remaining credit balance** on that screen, not only the bill amount.

**KAN-70 supersedes the customer order-detail UI for this.** Remaining credit is shown on the **customer profile**, per retailer, even when the limit is 0. See [customer-profile-credit.md](customer-profile-credit.md).

API already exposes `credit_limit` and `current_balance` on retailer–customer mapping. Remaining is limit minus used — **verify field math in code**, do not guess.

See also [../07-KEY-FLOWS/credit-khata.md](../07-KEY-FLOWS/credit-khata.md).
