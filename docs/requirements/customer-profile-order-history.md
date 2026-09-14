# Customer profile and order history

- **Ticket:** [OE-212](https://vin8003.atlassian.net/browse/OE-212) · backlog `F-0105` · [snapshot](../tickets/OE-212.md)
- **Implementation:** EXTEND (`RetailerCustomerMapping` + `Order` read model)
- **Depends on:** [retailer-organization.md](retailer-organization.md) (F-0001), unified `Order` POS/app (F-0049 / OE-131)

One shop customer record with purchase history across POS and app. Omnichannel is a source on `Order`, not a second CRM. Rewards / points stay on OE-220.

## EXISTING / EXTEND / NEW / SKIPPED

| Piece | Status |
|-------|--------|
| POS typeahead `search_pos_customers` / `verify_pos_customer` | EXISTING (no order rows; payloads unchanged) |
| CRM list `GET /api/customer/retailer/list/` | EXISTING (`customers` module) |
| CRM detail by id (10 recent, N+1) | EXISTING; not the phone 360 |
| `Order.customer` + `guest_mobile` / `source` pos\|app | EXISTING |
| Phone lookup → mapping + recent POS+app orders | EXTEND |
| Full history as paginated read (`export=1`) | EXTEND — gated by `orders.read` (closest catalog; no `crm.*`) |
| Duplicate merge | **MISSING / BLOCKER** — no merge primitives; not invented |
| Restaurant/retail share-identity org flag | **MISSING** — not invented. Same-org locations already share reads via `retailer__organization` |
| Rewards / Offer wallet | Out of scope (OE-220) |

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/customer/retailer/lookup/?phone=` | Retailer / org staff; `customers` module | Last-10 phone match in this org. Customer summary + up to 20 recent orders (both sources). Annotated `items_count`. Unknown phone **404**. Short phone **400**. |
| GET | `/api/customer/retailer/lookup/?phone=&export=1` | Same + `orders.read` | Paginated full history (`StandardResultsSetPagination`). Without `orders.read` → **403**, no rows leaked. |

Cross-tenant: org B looking up org A’s customer phone is **404**. Customer JWT is **403**.

## Security

- Tenant filter is `retailer__organization`, not a global user directory.
- Export is CRM-adjacent: catalog has no `customers.read`; `orders.read` is the existing code that authorizes reading order history. Owner is implicit admin.
- Cashiers (empty bootstrap role) can look up recent rows when the `customers` module is on; they cannot export full history.

## Not in this change

Duplicate merge, restaurant identity flag, FE CRM screens, rewards, CSV file download, live `*.ordereasy.win`.
