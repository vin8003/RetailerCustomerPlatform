# Payments

How money moves in OrderEasy — simple and shop-direct.

## Important principle

In most flows today, **payment goes directly to the shop**, not to OrderEasy. The system records *how* the customer paid for the shop’s books.

## Customer app payments

| Method | How it works |
|--------|--------------|
| **Cash on Delivery (COD)** | Customer pays cash when order arrives or at pickup |
| **UPI** | Customer pays shop’s UPI when receiving order |

You may not pay inside the app like a wallet — checkout selects the **intended** payment method.

## POS payments (counter)

| Method | How it works |
|--------|--------------|
| **Cash** | Till receives notes/coins |
| **UPI** | Customer scans shop QR |
| **Credit (khata)** | Amount added to customer ledger — pay later |
| **Split** | Combination e.g. part cash + part UPI |

Credit is common at kirana counters for trusted regulars.

## Customer credit vs payment

**Credit is not a payment gateway** — it is bookkeeping:

- Shop trusts customer to pay later
- Balance tracked in **Customers → ledger**
- Settlement happens offline (cash/UPI to shop)

## Supplier payments (shop side)

Separate from customer payments — **supplier khata** tracks what **shop owes wholesalers**. Record payments when you pay supplier.

## Rewards and discounts

- **Offers** reduce order total before payment
- **Reward points** may reduce amount due at checkout
- Shop still receives net amount (or records credit for balance)

## Reconciliation tips for retailers

| Daily | Weekly |
|-------|--------|
| Match COD collected vs delivered orders | Reconcile customer khata collections |
| Check UPI receipts vs UPI-tagged orders | Match supplier payments to khata |

## Future note

Payment integrations may expand over time. This wiki describes current kirana-friendly COD/UPI/credit patterns.

→ [Cart and checkout (customers)](../customer-guide/cart-and-checkout.md) · [POS billing](../retailer-guide/pos-billing.md) · [Customers and credit](../retailer-guide/customers-and-credit.md)
