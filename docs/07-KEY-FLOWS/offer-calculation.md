# Offer Calculation Engine

## Overview

The offer engine evaluates active offers against a cart (or POS items) and applies discounts or awards loyalty points according to configured rules.

## Supported Offer Types

| Offer Type | Description |
|------------|-------------|
| `bxgy` | Buy X Get Y (free or discounted) |
| `percentage` | Percentage discount on eligible items |
| `flat_amount` | Fixed amount off |
| `cart_value` | Discount when cart subtotal reaches a threshold |
| `tiered_price` / `flat_price` | Quantity-based or fixed pricing |

## Benefit Types

- **discount** → reduces the order total
- **credit_points** → awards loyalty points instead of (or in addition to) a discount

## Application Flow

![Offer Calculation Engine](../visuals/offer-calculation-engine.jpg)

*Illustrative diagram: Cart items enter the Offer Engine, which evaluates BXGY, percentage, flat amount, cart-value and other rules, then outputs applied discounts and/or loyalty points.*

```mermaid
flowchart TD
    Cart[Cart / POS Items] --> Fetch[Fetch active Offers<br/>filter by channel, dates, usage limits]
    Fetch --> Sort[Sort by priority descending]
    Sort --> Loop{For each Offer}

    Loop --> Eligible[Get eligible items<br/>match targets + exclusions]
    Eligible -->|No eligible items| Next
    Eligible -->|Has items| Benefit{benefit_type}

    Benefit -->|credit_points| Points[Calculate points to award]
    Benefit -->|discount| Type{offer_type}

    Type -->|bxgy| BXGY{bxgy_strategy}
    BXGY -->|mixed| Mix[Pool units → free cheapest items]
    BXGY -->|same_product| Same[Free quantity of same product]

    Type -->|percentage| Pct[Apply % discount]
    Type -->|flat_amount| Flat[Apply fixed amount off]
    Type -->|cart_value| CartVal[Apply if subtotal ≥ min_order_value]
    Type -->|tiered_price / flat_price| Tier[Apply tiered or fixed price]

    Points & Mix & Same & Pct & Flat & CartVal & Tier --> Apply[Update item prices / savings / applied_offers]
    Apply --> Next[Next Offer]
    Next --> Loop
    Loop -->|All offers processed| Result[Final discounted total + points]
```

## Key Rules

- Offers are processed in priority order.
- Stackability and exclusivity rules are respected.
- Channel filtering (POS vs App) is supported.
- Usage limits and validity dates are enforced.
