# Saleable quantity on retailer / POS product reads

- **Ticket:** [OE-132](https://vin8003.atlassian.net/browse/OE-132) · backlog `F-0029` (thin slice) · [snapshot](../tickets/OE-132.md)
- **Implementation:** EXTEND (existing `Product.saleable_quantity()` on retailer/POS reads)
- **Depends on:** [product-batch-expiry.md](product-batch-expiry.md)

Retailer and POS product **reads** expose `saleable_quantity` from the existing helper: sum of **active, non-expired** lots (null expiry stays saleable). Gross `quantity` is unchanged and still includes expired lots until write-off.

This is not ATP. There are no reservations, holds, or ledger available-to-promise.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.saleable_quantity()`, `saleable_quantity_annotation()`, `cache_saleable_quantities()` | EXISTING (OE-136) |
| Gross `Product.quantity` on the same payloads | EXISTING, locked |
| `saleable_quantity` on retailer list / search / detail and POS `no_page` | EXTEND |
| Reservations, ATP by location, multi-shop transfer | Out of scope |

## API

| Method | Path | Who | `saleable_quantity` |
|--------|------|-----|---------------------|
| GET | `/api/products/?no_page=true` | Authenticated retailer | Yes (POS catalog) |
| GET | `/api/products/` | Authenticated retailer | Yes (paginated list) |
| GET | `/api/products/search/` | Authenticated retailer | Yes |
| GET | `/api/products/<id>/` | Authenticated retailer | Yes |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Omitted |

`quantity` stays the gross on-hand total. `saleable_quantity` uses the helper only. List/search/POS paths call `Product.cache_saleable_quantities()` so the helper does not SUM per row.

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's product (empty list / **404**).

## Not in this change

Full F-0029 foundation (reservations, ledger ATP, multi-shop transfer), OE-102, #103, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
