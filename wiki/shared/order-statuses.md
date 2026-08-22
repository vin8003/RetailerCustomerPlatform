# Order statuses explained

Orders move through clear stages so **customers know what to expect** and **shops know what to do next**.

![Order status lifecycle](../../docs/visuals/order-status-lifecycle.jpg)

*Illustration: main path from pending to delivered, plus cancel and approval branches.*

## Status reference

| Status | For customers | For retailers |
|--------|---------------|---------------|
| **Pending** | "Shop received my order" | Review and confirm, modify, or cancel |
| **Confirmed** | "Shop accepted — they will prepare it" | Start picking items |
| **Processing** | "Being prepared" | Actively packing |
| **Packed** | "Ready for next step" | Hand to delivery or tell pickup customer |
| **Out for delivery** | "On the way" (delivery only) | Your staff is delivering |
| **Ready for pickup** | "Come collect" (pickup) | Customer notified to visit shop |
| **Delivered** | "Done" | Sale complete; collect COD if needed |
| **Cancelled** | "Did not happen" | No fulfilment |
| **Waiting for customer approval** | "Shop changed my order — I must accept" | Wait before packing |
| **Returned** | "Sent back after delivery" | Process return per policy |

## Happy path — delivery order

```
Pending → Confirmed → Processing → Packed → Out for delivery → Delivered
```

## Happy path — pickup order

```
Pending → Confirmed → Processing → Packed → Delivered
```

(Pickup may show "ready for pickup" before delivered — depends on shop workflow.)

## When shop modifies your order

If something is out of stock, shop may change items or quantities.

1. Status becomes **Waiting for customer approval**
2. Customer reviews changes in app
3. **Accept** → order continues as **Confirmed**
4. **Reject** → order may cancel

Shops should message customer via chat when modifying.

## Cancellation

Either side may cancel while still **Pending**. After confirm, cancellation needs coordination — contact shop.

## No separate delivery company

**Out for delivery** means the **shop’s own person** is delivering. There is no OrderEasy rider to track on a map.

## Push notifications

Both apps can notify on status change — enable notifications for fewer "where is my order?" calls.

→ [Track your order (customers)](../customer-guide/track-your-order.md) · [Online orders (retailers)](../retailer-guide/online-orders.md)
