# Customers and credit (khata)

**Customers** in OrderEasy is your shop’s CRM — everyone who buys from you, whether at counter or online.

## Customer list

Open **Customers** to see:

- Name and phone
- Total orders
- Credit balance (if any)
- Notes or flags (e.g. blacklist)

Search by name or phone when billing at POS or reviewing accounts.

## Adding customers

Customers are often created automatically when:

- Someone signs up on the customer app and orders from you
- Staff attaches a new person at POS
- You add manually from Customers → Add

Keep phone numbers accurate for OTP login and delivery calls.

## Customer credit (udhaar / khata)

Trusted regulars often buy **on credit** and settle later — classic kirana khata.

![Credit and khata system](../../docs/visuals/credit-khata-system.jpg)

*Illustration: how customer credit connects to POS and ledger.*

### How credit works

| Event | Effect on balance |
|-------|-------------------|
| POS sale on **credit** | Customer owes more |
| Customer **pays** you | Balance reduces |
| Return or adjustment | Balance corrected per policy |

### Credit limit

You can set a **maximum credit** per customer. POS blocks new credit sales above limit (unless you change policy).

### Recording payment

When customer pays off khata:

1. Open **Customer detail** → ledger
2. Record **payment received** with amount
3. Balance updates

Payments happen **offline** (cash/UPI to you) — OrderEasy tracks the ledger, not the bank transfer.

## Customer detail page

From a customer profile you can see:

- Order history
- Credit ledger entries
- Contact info
- Nickname (how staff know them)

## Blacklist

For problematic accounts you can **blacklist** — blocks new credit or orders per your settings. Use carefully and document why in notes.

## POS customer search

At billing, typeahead shows **only your customers** by name. Helps attach the right person quickly during rush hour.

## Online vs counter customers

Same customer record whether they:

- Only shop in person
- Only order online
- Do both

Encourage regulars to use the app — they see same prices and you see unified history.

## Privacy

Customer data belongs to **your shop**. Use it only for shop business. Do not share lists externally.

→ [POS billing](pos-billing.md) · [Credit flow in docs](../docs/07-KEY-FLOWS/credit-khata.md)
