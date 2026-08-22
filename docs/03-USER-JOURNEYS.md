# 03 – User journeys

Illustrative journeys for humans and agents. Images contain **no real customer data**. Text and Mermaid are the source of the rules; JPGs are supporting visuals.

Related work: [KAN-53](requirements/retailer-store-location.md), [KAN-54](requirements/customer-location-at-start.md). Ticket snapshots stay under [`tickets/`](tickets/).

## Customer journey

![Customer Journey](visuals/customer-journey.jpg)

*Discover nearby stores → browse catalog → cart → checkout → track order → rewards.*

```mermaid
flowchart LR
    Discover[Discover stores] --> Browse[Browse catalog]
    Browse --> Cart[Cart]
    Cart --> Checkout[Checkout]
    Checkout --> Track[Track status]
    Track --> Rewards[Rewards]
```

**Key points**

- Customers use `customer_ordereasy_njs` (web + Capacitor) against the Django API.
- Guest cart exists before signup; tokens must not wipe it (see [guest-cart-signup.md](07-KEY-FLOWS/guest-cart-signup.md)).
- At start, the app should ask for location rather than forcing a manual pin first ([customer-location-at-start.md](requirements/customer-location-at-start.md)). Manual override may remain.
- Pickup and delivery are `Order.delivery_mode` on the backend. There is **no** separate delivery/rider app ([ADR-001](decisions/ADR-001-no-delivery-app.md)).

## Retailer POS and online orders

![Retailer POS Order Handling](visuals/retailer-pos-order-handling.jpg)

*POS terminal for walk-in billing plus online order status handling in the retailer app.*

```mermaid
flowchart TB
    subgraph POS [Walk-in POS]
        Search[Product search / barcode] --> Line[Cart lines]
        Line --> Pay[Take payment]
    end
    subgraph Online [Online orders]
        Pending[Pending] --> Confirm[Confirm / modify / cancel]
        Confirm --> Fulfill[Process → packed → deliver or pickup]
    end
```

**Key points**

- Retailer app: `retailer_ordereasy_njs` at `https://retailer.ordereasy.win`.
- POS customer typeahead lists **this retailer’s customers only**, with name ([pos-customer-typeahead.md](requirements/pos-customer-typeahead.md)).
- Store pin is set in the retailer app ([retailer-store-location.md](requirements/retailer-store-location.md)).
- Order status rules live in [order-lifecycle.md](07-KEY-FLOWS/order-lifecycle.md).

## Scanner to catalog

![Scanner to Catalog Flow](visuals/scanner-to-catalog-flow.jpg)

*Flutter scanner → upload session → scan/OCR → review → edit → commit to catalog.*

```mermaid
flowchart LR
    Scan[Flutter scanner] --> Session[Upload session]
    Session --> OCR[Scan / OCR]
    OCR --> Review[Review]
    Review --> Edit[Edit]
    Edit --> Catalog[Commit to catalog]
```

**Key points**

- Scanner is `buyeasy_retailer_scanner` (Flutter + ML Kit). It talks to the same Django API via upload sessions.
- Catalog truth is the backend, not the scanner device.
- Crash/logging work for intensive scanning is **ticket work**, not a durable architecture change: [tickets/KAN-18.md](tickets/KAN-18.md).
