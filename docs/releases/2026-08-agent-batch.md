# Release: agent batch Aug 2026

Coordinated release across three app repos. **Do not mark Jira tickets Done until Vineet deploys.**

## Tickets

| Ticket | Backend (RCP) | Retailer FE | Customer FE |
|--------|---------------|-------------|-------------|
| [KAN-17](https://vin8003.atlassian.net/browse/KAN-17) | FBT API | — | Cart + PDP lane |
| [KAN-19](https://vin8003.atlassian.net/browse/KAN-19) | — | — | PDP add-to-cart position |
| [KAN-20](https://vin8003.atlassian.net/browse/KAN-20) | — (docs) | Event-driven stats | — |
| [KAN-49](https://vin8003.atlassian.net/browse/KAN-49) | Parent `is_available` decoupled | Parent visibility toggle | — |
| [KAN-63](https://vin8003.atlassian.net/browse/KAN-63) | Hide OOS in customer APIs | — | — |
| [KAN-70](https://vin8003.atlassian.net/browse/KAN-70) | `GET /api/customer/credit/all/` | — | Profile credit |
| [KAN-71](https://vin8003.atlassian.net/browse/KAN-71) | — (docs) | — | Location gate |
| [KAN-72](https://vin8003.atlassian.net/browse/KAN-72) | Batch barcode search | — | — |
| [KAN-73](https://vin8003.atlassian.net/browse/KAN-73) | Online shoppers in POS typeahead | — | — |
| [KAN-74](https://vin8003.atlassian.net/browse/KAN-74) | — | Dashboard customer count | — |
| [KAN-77](https://vin8003.atlassian.net/browse/KAN-77) | Returned filter + sales return status | Returned tab resilience | — |
| [KAN-78](https://vin8003.atlassian.net/browse/KAN-78) | Supplier edit + safe deactivate | Khata edit/deactivate + picker `?is_active=true` | — |
| [KAN-79](https://vin8003.atlassian.net/browse/KAN-79) | Supplier search without invalid `email` | Search-miss empty copy | — |

## Release PRs

- **Backend:** `RetailerCustomerPlatform` → `cursor/release-agent-batch-9558`
- **Retailer:** `retailer_ordereasy_njs` → `cursor/release-agent-batch-9558`
- **Customer:** `customer_ordereasy_njs` → `cursor/release-agent-batch-9558`

## Deploy sequence

1. Merge **RCP** release PR to `main`
2. Merge **both FE** release PRs to `main` (can be parallel)
3. Open RCP PR `main` → `deploy/dev` (Oracle GHA deploy)
4. Build + deploy `retailer_web_build` and `customer_web_build` to Cloudflare Pages

## New / changed APIs

- `GET /api/customer/credit/all/` — retailer-wise credit balances (KAN-70)
- `GET /api/products/retailer/<id>/frequently-bought-together/?product_ids=` — FBT (KAN-17)
- `GET /api/orders/?status=returned` — matches sales returns (KAN-77)
- Customer product listing endpoints omit tracked OOS (KAN-63)
- Product search matches batch barcodes (KAN-72)
- POS `search-pos-customers` includes prior online shoppers (KAN-73)
- `PATCH /api/products/erp/suppliers/<id>/` with `is_active` deactivates without deleting history (KAN-78)
- `GET /api/products/erp/suppliers/?is_active=true` for new-purchase pickers (KAN-78)
- `GET /api/products/erp/suppliers/?search=` searches company/contact/phone only (KAN-79)

## Supersedes

Per-ticket PRs #55–#64, #66, #67 (RCP), #19–#24 (retailer), #13–#16 (customer). Do **not** merge closed broken PRs #57 / #58.
