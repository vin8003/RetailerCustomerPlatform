# All apps explained

OrderEasy is one product spread across **five apps**. Each has a clear job. Together they cover everything from marketing to counter billing.

## At a glance

| App | For whom | URL / platform | Main job |
|-----|----------|----------------|----------|
| **Marketing website** | Everyone | [ordereasy.win](https://ordereasy.win) | Explain product; link to customer or retailer app |
| **Customer app** | Shoppers | [customer.ordereasy.win](https://customer.ordereasy.win) | Browse one shop, order, track, rewards |
| **Retailer app** | Shop owners & staff | [retailer.ordereasy.win](https://retailer.ordereasy.win) | POS, orders, stock, suppliers, offers |
| **Scanner app** | Shop staff | Android install | Fast barcode/photo capture for catalog |
| **Backend** | (invisible to users) | api.ordereasy.win | Stores all data; powers every app |

Customers and retailers only need the first three URLs in daily life. Scanner is optional but valuable for setup.

---

## Marketing website (ordereasy.win)

**Who:** Anyone curious about OrderEasy

**What it does:**
- Explains "software for your kirana, not a marketplace"
- Two buttons: open retailer app or customer app
- Sets expectations (no delivery company, one shop focus)

**What it does not do:** Orders, payments, or account management

---

## Customer app (customer_ordereasy_njs)

**Who:** Local shoppers ordering from a shop they know

**What customers do:**
- Share location → see nearby shops
- Pick **one shop** → browse catalog
- Cart → checkout (delivery/pickup, COD/UPI)
- Track orders, chat, wishlist, rewards

**Works on:** Phone browser (web app); Android wrapper available

**Does not:** Show marketplace of unrelated sellers; provide OrderEasy delivery

→ Full guide: [Customer guide](../customer-guide/README.md)

---

## Retailer app (retailer_ordereasy_njs)

**Who:** Kirana owner and counter staff

**What retailers do:**
- **Dashboard** — today’s numbers
- **POS** — bill walk-in customers
- **Orders** — fulfil online orders
- **Products** — catalog and stock
- **Purchases** — stock from suppliers
- **Suppliers** — khata (what you owe)
- **Customers** — CRM and credit (what they owe you)
- **Offers** — promotions and loyalty
- **Reports & reviews**

**Works on:** Browser on phone or computer

→ Full guide: [Retailer guide](../retailer-guide/README.md)

---

## Scanner app (buyeasy_retailer_scanner)

**Who:** Staff walking the shop floor

**What it does:**
- Login with retailer credentials
- Create **upload sessions**
- Scan barcodes + photograph labels
- OCR helps fill name and price
- Sync to cloud for manager review

**Does not:** Replace retailer app for editing catalog or billing

→ Full guide: [Scanner guide](../scanner-guide/README.md)

---

## Backend (RetailerCustomerPlatform)

**Who:** No direct users — powers everything

**What it stores:**
- All shops, products, stock, batches
- All orders and status history
- Customer and supplier ledgers
- Offers, points, reviews
- Scanner upload sessions

**Why it matters to you:** One stock number everywhere. Sell at POS → online quantity drops. Customer orders → POS stock drops.

Developers and agents find technical docs in [`docs/`](../docs/DOCUMENTATION.md).

---

## Which app do I open?

| I want to… | Open |
|------------|------|
| Order groceries from my kirana | customer.ordereasy.win |
| Bill a walk-in customer | retailer.ordereasy.win → POS |
| Confirm an online order | retailer.ordereasy.win → Orders |
| Scan 200 new products | Scanner app → then retailer Bulk Add |
| Learn what OrderEasy is | ordereasy.win |

→ [How everything works together](how-it-works-together.md)
