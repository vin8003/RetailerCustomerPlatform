# Delivery fee and discount on order list

- **Ticket:** [OE-301](https://vin8003.atlassian.net/browse/OE-301) · [snapshot](../tickets/OE-301.md)
- **Implementation:** EXTEND (echo existing `Order.delivery_fee` and `Order.discount_amount` on list)
- **Related:** [order-lifecycle.md](../07-KEY-FLOWS/order-lifecycle.md)

Retailer (and customer) order list rows include top-level `delivery_fee` and `discount_amount` with the same values already returned by order detail. This is a field echo, not fee math, payment write, or a status-machine change.

`null` stays `null`. Values are Decimal-equal to detail for the same order. No extra queryset joins — both columns live on `Order`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `delivery_fee` / `discount_amount` on `OrderDetailSerializer` | EXISTING |
| `delivery_fee` / `discount_amount` on `Order` | EXISTING |
| Same keys on `OrderListSerializer` | EXTEND (OE-301) |
| Fee calculation / payment write / FE | Out of scope |

## API

| Method | Path | Who | Fields |
|--------|------|-----|--------|
| GET | `/api/orders/current/` | Authenticated customer or retailer | List row echoes detail `delivery_fee` + `discount_amount` |
| GET | `/api/orders/history/` | Authenticated customer or retailer | Same shared list serializer |
| GET | `/api/orders/<id>/` | Authenticated customer or retailer (tenant-scoped) | EXISTING |

Unauthenticated list → **401**. Tenant B cannot read tenant A's order.

`ProductSearchSerializer` Meta and POS `?no_page=true` are not part of this slice (OE-302 / search chain stay isolated).

## Not in this change

Fee math, payment write, FE, POS `no_page`, search Meta, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, Jira Done, live `*.ordereasy.win`.
