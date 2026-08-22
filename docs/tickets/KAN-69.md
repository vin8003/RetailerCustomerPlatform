---
id: KAN-69
title: Customer city map of retailers
knowledge_class: durable
owning_repo: customer_ordereasy_njs
durable_docs:
  - docs/requirements/customer-retailer-city-map.md
  - docs/03-USER-JOURNEYS.md
jira: https://vin8003.atlassian.net/browse/KAN-69
---

# KAN-69 Customer city map of retailers

Work snapshot. Durable: [customer-retailer-city-map.md](../requirements/customer-retailer-city-map.md).

`/retailers` becomes a Google map of the selected city centred on the customer (default address in that city → GPS → city geocode). Shops with coordinates are markers; shops without one ride a rail at the edge of the viewport and are never plotted at a fake position. A distance-sorted list peeks at the bottom and takes over the page if Maps cannot load. Location changes happen in a sheet on `/retailers` and on store home instead of a trip to `/city-selection`. Local mock (`NEXT_PUBLIC_MOCK_RETAILERS=1`) stands in for the list API until backend deploy.

Backend: `latitude`/`longitude` added to `RetailerListSerializer`, plus a `filter_by_radius` query flag (default `true`) so the map can request distances without dropping shops outside the delivery radius.

Built on KAN-68 (Tailwind + shadcn, indigo). Related: KAN-53 (shop pin), KAN-54 (GPS at start), KAN-64 (city/state dropdowns). Out of scope: geocoding missing shop pins, clustering, catalog-home map, delivery app, Leaflet. QA on customer.ordereasy.win after deploy.
