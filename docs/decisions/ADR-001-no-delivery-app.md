# ADR-001: Do not build a delivery app yet

- **Status:** Accepted
- **Date:** 2026-08-19
- **Tickets:** [KAN-58](https://vin8003.atlassian.net/browse/KAN-58)
- **Work snapshot:** [../tickets/KAN-58.md](../tickets/KAN-58.md)

## Context

KAN-58 appeared on the board as “delivery app” with no spec, no rider identity, and no client. The backend already models shop-level dispatch (`Order.delivery_mode`, `out_for_delivery`, `OrderDelivery` with name/phone strings). There is no rider User role, no assign/GPS/POD API, and no third client app.

## Decision

Do **not** start a delivery/rider app. Do not create a new repository for it.

Retailer already owns order status. Customer already sees status and FCM. A third app would duplicate both unless there is a distinct rider role — which the code does not have.

This is shop-level dispatch (name + phone), not a courier-network buy (Shiprocket/Dunzo).

## Consequences

- Fill `OrderDelivery` from the **retailer app** (assign name/phone, mark `out_for_delivery`) and show it on the **customer** order screen, using the existing Django API, if/when that work is needed.
- A rider Capacitor app is a later product, not this ticket.
- Agents and builders must not invent a delivery-app workstream from KAN-58.

## Snapshot source

Copied from Confluence; Confluence page retained. GitBook copy retained as presentation.
