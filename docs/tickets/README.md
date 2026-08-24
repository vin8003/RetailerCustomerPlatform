# Ticket work snapshots

These files are **copies of Confluence pages** that were also copied to GitBook. They exist so an agent can clone this repo and read the material **without GitBook**.

They are **not** Jira. Status, assignee, and “is it done?” live in Jira.

They are **not** automatically durable knowledge. Many pages are builder briefs, bug investigations, or ship notes.

## How to use

1. Open `KAN-nnn.md` for links (Jira, Confluence, GitBook) and the snapshot body.
2. If `knowledge_class` is `durable` or `mixed`, follow `durable_docs` in the front matter — that is the lasting object to update.
3. If `knowledge_class` is `temporary`, keep the snapshot for context; do not promote the whole ticket into architecture docs.
4. Update durable docs + this snapshot via Git PR. Do not delete Confluence. Do not remove Confluence links from Jira.

## Index

| File | Class | Durable knowledge |
|------|-------|-------------------|
| [KAN-11.md](KAN-11.md) | mixed | [retailer-web-mobile](../requirements/retailer-web-mobile.md) |
| [KAN-14.md](KAN-14.md) | durable | [guest-cart-signup](../07-KEY-FLOWS/guest-cart-signup.md), [ADR-002](../decisions/ADR-002-deferred-token-guest-cart.md) |
| [KAN-16.md](KAN-16.md) | durable | [promotional-email](../requirements/promotional-email.md) |
| [KAN-17.md](KAN-17.md) | durable | [frequently-bought-together](../requirements/frequently-bought-together.md) |
| [KAN-18.md](KAN-18.md) | temporary | — (crash investigation / logging work) |
| [KAN-19.md](KAN-19.md) | temporary | — (PDP add-button polish) |
| [KAN-20.md](KAN-20.md) | durable | [order-stats-polling](../requirements/order-stats-polling.md) |
| [KAN-29.md](KAN-29.md) | durable | [pos-customer-typeahead](../requirements/pos-customer-typeahead.md) |
| [KAN-46.md](KAN-46.md) | durable | [daily-db-backup](../requirements/daily-db-backup.md) |
| [KAN-47.md](KAN-47.md) | durable | [google-social-login](../07-KEY-FLOWS/google-social-login.md) |
| [KAN-51.md](KAN-51.md) | temporary | — (product-group search bug) |
| [KAN-53.md](KAN-53.md) | durable | [retailer-store-location](../requirements/retailer-store-location.md) |
| [KAN-54.md](KAN-54.md) | durable | [customer-location-at-start](../requirements/customer-location-at-start.md) |
| [KAN-55.md](KAN-55.md) | temporary | — (history row → order detail) |
| [KAN-56.md](KAN-56.md) | durable | [supplier-mobile-optional](../requirements/supplier-mobile-optional.md) |
| [KAN-58.md](KAN-58.md) | durable | [ADR-001](../decisions/ADR-001-no-delivery-app.md) |
| [KAN-60.md](KAN-60.md) | durable | [purchase-bill-image](../requirements/purchase-bill-image.md) |
| [KAN-61.md](KAN-61.md) | durable | [credit-remaining-balance](../requirements/credit-remaining-balance.md) |
| [KAN-62.md](KAN-62.md) | durable | [inactive-product-edit](../requirements/inactive-product-edit.md) |
| [KAN-63.md](KAN-63.md) | durable | [customer-hide-oos](../requirements/customer-hide-oos.md) |
| [KAN-69.md](KAN-69.md) | durable | [customer-retailer-city-map](../requirements/customer-retailer-city-map.md) |
| [KAN-70.md](KAN-70.md) | durable | [customer-profile-credit](../requirements/customer-profile-credit.md) |
| [KAN-72.md](KAN-72.md) | durable | [product-search-barcodes](../requirements/product-search-barcodes.md) |

Skipped (no Confluence page at migration time): KAN-48, KAN-49, KAN-52, KAN-57.

## Duplication (intentional)

The same text may exist in Confluence, GitBook, and `tickets/*.md`. **Git `docs/` is canonical going forward.** Confluence and GitBook copies are retained; do not delete them in this effort.
