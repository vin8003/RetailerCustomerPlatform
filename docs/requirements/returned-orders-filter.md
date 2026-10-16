# Returned orders filter (retailer app)

- **Status:** Implemented
- **Ticket:** [KAN-77](https://vin8003.atlassian.net/browse/KAN-77) · [snapshot](../tickets/KAN-77.md)
- **Apps:** `RetailerCustomerPlatform` · `retailer_ordereasy_njs`

The retailer Orders **Returned** tab must list every order with a sales return, not only rows where `order.status='returned'`.

## Problem

POS sales returns often left `order.status` as `delivered`. Filtering strictly on `status=returned` returned an empty list or API errors.

## Backend rules

- `GET /api/orders/` with `status=returned` matches:
  - `order.status = 'returned'`, **or**
  - any order with at least one `SalesReturn` row (`Exists` subquery, no join blow-up).
- **Full** sales returns set `order.status` to `returned` via `returns/services.py`.
- **Partial** returns keep `delivered` but still appear on the Returned tab.
- Order list serialization is walk-in safe for `customer_average_rating` (missing customer profile must not 500).

## Retailer UI

- Parse paginated history responses safely.
- If the API errors, fall back to client-side filter on `is_returned` when present in the payload.
