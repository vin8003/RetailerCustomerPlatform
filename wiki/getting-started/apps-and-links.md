# Apps and links

OrderEasy is made up of a few apps that work together. Here is what each one is for and where to open it.

## Live apps

| App | Who uses it | Open it | What it does |
|-----|-------------|---------|--------------|
| **Customer app** | Shoppers | [customer.ordereasy.win](https://customer.ordereasy.win) | Browse a shop, order, track, rewards |
| **Retailer app** | Shop owners & staff | [retailer.ordereasy.win](https://retailer.ordereasy.win) | POS, orders, stock, suppliers, offers |
| **Scanner app** | Shop staff (phone) | Install on Android (from your shop) | Scan barcodes and photograph products for bulk catalog upload |
| **Website** | Everyone | [ordereasy.win](https://ordereasy.win) | Learn about OrderEasy and choose customer or retailer |

## Do I need to install anything?

| User | Install needed? |
|------|-----------------|
| **Customer** | No — open the customer link in your phone browser. An Android app wrapper exists but the web app works without install. |
| **Retailer** | No — the retailer dashboard works in a browser on phone or computer. |
| **Scanner** | Yes — this is a separate Android app for fast product capture at the shelf. |

## Which app talks to which?

All apps connect to the **same backend** (the shop’s data lives in one place):

```
Customer app  ──┐
Retailer app  ──┼──►  OrderEasy backend  ◄──  Your shop data
Scanner app   ──┘
```

That is why stock sold at the counter immediately affects what customers see online, and vice versa.

## Related repositories (for developers)

| Component | Code repository |
|-----------|-----------------|
| Backend API | `RetailerCustomerPlatform` (this repo) |
| Customer web app | `customer_ordereasy_njs` |
| Retailer web app | `retailer_ordereasy_njs` |
| Scanner mobile app | `buyeasy_retailer_scanner` |
| Marketing site | `ordereasy-landing` |

Customers and retailers do not need to know about repositories — this table is for anyone exploring the full project.

→ [Getting started for customers](for-customers.md) · [Getting started for retailers](for-retailers.md)
