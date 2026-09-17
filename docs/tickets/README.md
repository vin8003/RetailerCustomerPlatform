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
| [KAN-69.md](KAN-69.md) | durable | [customer-retailer-city-map](../requirements/customer-retailer-city-map.md) |
| [OE-97.md](OE-97.md) | durable | [retailer-organization](../requirements/retailer-organization.md) |
| [OE-98.md](OE-98.md) | durable | [shop-staff-roles](../requirements/shop-staff-roles.md) |
| [OE-182.md](OE-182.md) | durable | [api-versioning](../requirements/api-versioning.md) |
| [OE-281.md](OE-281.md) | durable | [order-lifecycle](../07-KEY-FLOWS/order-lifecycle.md) |
| [OE-190.md](OE-190.md) | durable | [pos-saleable-products](../requirements/pos-saleable-products.md) |
| [OE-127.md](OE-127.md) | durable | [inventory-adjust-permission](../requirements/inventory-adjust-permission.md) |
| [OE-103.md](OE-103.md) | durable | [parent-child-pack-skus](../requirements/parent-child-pack-skus.md) |
| [OE-191.md](OE-191.md) | durable | [pack-children-reads](../requirements/pack-children-reads.md) |
| [OE-192.md](OE-192.md) | durable | [group-variants-reads](../requirements/group-variants-reads.md) |
| [OE-136.md](OE-136.md) | durable | [product-batch-expiry](../requirements/product-batch-expiry.md) |
| [OE-144.md](OE-144.md) | durable | [product-batch-expiry](../requirements/product-batch-expiry.md) |
| [OE-141.md](OE-141.md) | durable | [damage-expiry-write-off](../requirements/damage-expiry-write-off.md) |
| [OE-106.md](OE-106.md) | durable | [app-vs-pos-prices](../requirements/app-vs-pos-prices.md) |
| [OE-124.md](OE-124.md) | durable | [product-photo-bulk-import](../requirements/product-photo-bulk-import.md) |
| [OE-143.md](OE-143.md) | durable | [khata-credit-lock](../requirements/khata-credit-lock.md) |
| [OE-212.md](OE-212.md) | durable | [customer-profile-order-history](../requirements/customer-profile-order-history.md) |
| [OE-220.md](OE-220.md) | durable | [shop-rewards-otp-redeem](../requirements/shop-rewards-otp-redeem.md) |
| [OE-100.md](OE-100.md) | durable | [suppliers](../requirements/suppliers.md) |
| [OE-146.md](OE-146.md) | durable | [block-negative-stock](../requirements/block-negative-stock.md) |
| [OE-170.md](OE-170.md) | durable | [additional-barcodes-lookup](../requirements/additional-barcodes-lookup.md) |
| [OE-112.md](OE-112.md) | durable | [compare-supplier-cost](../requirements/compare-supplier-cost.md) |
| [OE-118.md](OE-118.md) | durable | [purchase-margin-preview](../requirements/purchase-margin-preview.md) |
| [OE-210.md](OE-210.md) | durable | [expiry-batch-list](../requirements/expiry-batch-list.md) |
| [OE-132.md](OE-132.md) | durable | [saleable-quantity-reads](../requirements/saleable-quantity-reads.md) |

Skipped (no Confluence page at migration time): KAN-48, KAN-49, KAN-52, KAN-57, KAN-63.

## Duplication (intentional)

The same text may exist in Confluence, GitBook, and `tickets/*.md`. **Git `docs/` is canonical going forward.** Confluence and GitBook copies are retained; do not delete them in this effort.
