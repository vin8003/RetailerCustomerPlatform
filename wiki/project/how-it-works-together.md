# How everything works together

This page ties the whole OrderEasy project together — without technical jargon.

## The big picture

One **local shop** uses OrderEasy to:

1. Run the **counter** (POS)
2. Manage **stock and suppliers**
3. Take **online orders** from regular customers
4. Track **credit** on both sides (customer udhaar + supplier dues)

All of that shares **one set of numbers** in the cloud.

```
                    ┌─────────────────────┐
                    │   Your shop data    │
                    │  (products, stock,  │
                    │   orders, khata)    │
                    └──────────┬──────────┘
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    Customer app          Retailer app         Scanner app
    (order online)        (POS + manage)       (capture SKUs)
```

## Example: one product, three touchpoints

**Product:** 1kg Tata Salt, ₹28, 40 bags in stock

| What happens | App involved | Stock after |
|--------------|--------------|-------------|
| Customer orders 2 bags online | Customer app | 38 bags |
| Walk-in buys 3 bags at counter | Retailer POS | 35 bags |
| Supplier delivers 50 bags | Retailer Purchases | 85 bags |
| Staff scans 10 new SKUs | Scanner → Bulk add | New products live |

Customer always sees **current** availability. No separate "online stock" notebook.

## Example: one customer, two channels

**Priya** is a regular:

| Channel | What Priya does | What shop sees |
|---------|-----------------|----------------|
| **In shop** | Buys on credit at POS | Customer ledger +₹500 |
| **At home** | Orders dal on customer app | New online order pending |
| **Later** | Pays ₹500 cash | Ledger payment −₹500 |

Same **Priya** record in Customers — whether she uses app or not.

## Example: online order end-to-end

| Step | Customer | Shop |
|------|----------|------|
| 1 | Adds items, checkout, places order | Notification: Pending order |
| 2 | Sees "Pending" | Reviews, confirms |
| 3 | Sees "Processing" | Picks from shelf (same stock as POS) |
| 4 | Sees "Out for delivery" | Staff delivers |
| 5 | Pays COD, sees "Delivered" | Marks delivered, day’s revenue updates |

If shop is out of rice, they **modify** order → Priya gets **approval** request.

## Example: setting up a new shop

| Week | Activities | Apps used |
|------|------------|-----------|
| 1 | Sign up, profile, hours, location | Retailer |
| 1–2 | Add products (scanner + review) | Scanner + Retailer |
| 2 | Train staff on POS | Retailer |
| 2 | Test order from owner’s phone | Customer + Retailer |
| 3 | Tell regulars the customer link | Marketing word-of-mouth |
| Ongoing | Purchases, offers, khata | Retailer |

## What stays in sync automatically

| Data | Synced across |
|------|---------------|
| Product prices | POS + customer app |
| Stock levels | POS + online orders + purchases |
| Order status | Retailer actions → customer tracking |
| Offers | POS + checkout (when configured) |
| Customer credit | POS sales + ledger |

## What you manage manually

| Task | Why manual |
|------|------------|
| Physical delivery | Your staff, your routes |
| Collecting COD / UPI | Money goes to your till |
| Supplier payments | You pay wholesaler offline |
| Customer trust on credit | Your judgement on limits |

## Repositories (for the full project map)

| Piece | Repository name |
|-------|-----------------|
| Backend API + this wiki | `RetailerCustomerPlatform` |
| Customer web app | `customer_ordereasy_njs` |
| Retailer web app | `retailer_ordereasy_njs` |
| Scanner mobile app | `buyeasy_retailer_scanner` |
| Landing page | `ordereasy-landing` |

## Where to go next

| Audience | Start |
|----------|-------|
| Customer | [Getting started for customers](../getting-started/for-customers.md) |
| Retailer | [Getting started for retailers](../getting-started/for-retailers.md) |
| Either | [FAQ](../faq/common-questions.md) |
| Developer | [docs/DOCUMENTATION.md](../docs/DOCUMENTATION.md) |
