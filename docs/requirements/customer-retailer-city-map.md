# Customer retailer city map

- **Ticket:** [KAN-69](https://vin8003.atlassian.net/browse/KAN-69) · [snapshot](../tickets/KAN-69.md)
- **Apps:** `customer_ordereasy_njs` (live https://customer.ordereasy.win) · `RetailerCustomerPlatform` (list API)

`/retailers` is a map of the selected city with the customer in the middle, not a flat card list.

## Rules

- **The customer is the centre.** Priority: default `CustomerAddress` with coordinates (read `is_default`, do not assume the first row) → last persisted GPS fix → one geocode of the selected city. If none resolve, the page falls back to the list.
- **Never invent a shop coordinate.** A shop without `latitude`/`longitude` is shown on a rail at the edge of the map viewport, marked as having no pin, and sorts last everywhere. Retailers set their own pin ([retailer-store-location.md](retailer-store-location.md), KAN-53).
- **The map must not hide shops.** `GET /api/retailers/` filters out shops outside `delivery_radius` when `lat`/`lng` are sent. The map sends `filter_by_radius=false` so it still gets `distance` without losing stores. The flag defaults to the filtering behaviour, so existing clients are unchanged.
- **The distance list is a fallback, not decoration.** It is always on the page, collapsed at the bottom, sorted nearest first with unlocated shops last. When Google Maps fails to load or the API key is missing, the list becomes the whole page and is enough to choose a store.
- **Location changes happen in place.** The header chip on `/retailers` and on store home (`/retailer?id=`) opens a sheet with saved addresses, current location, and city/state. `/city-selection` remains only for the case where there is no location at all. Choosing a saved address here never writes to the customer's address book. Picking a city centres the map on that city, not on a saved address in a different city.
- **Local development does not wait on backend deploy.** `NEXT_PUBLIC_MOCK_RETAILERS=1` (dev only) serves retailers, addresses, profile, and notifications from `customer_ordereasy_njs/src/services/mockRetailers.ts`. Mock shops are anchored to the selected city; some sit outside a 5 km radius and some have no coordinates, which is what the rail and nearest-first list are for.

## API contract

`RetailerListSerializer` exposes nullable `latitude` and `longitude`. The map calls:

```
GET /api/retailers/?city=&state=&lat=&lng=&filter_by_radius=false&page_size=100
```

`distance` is kilometres from the supplied `lat`/`lng` (JSON number), or `null` when either side has no coordinates. `latitude` / `longitude` are DRF decimal strings; `delivery_radius` is an integer km. `filter_by_radius` is true for `true`/`1`/`yes`, false for `false`/`0`/`no`, and keeps the default (filter on) when omitted, blank, or unrecognised. When `lat`/`lng` are present, `filter_by_radius=false` skips both radius and serviceable-pincode exclusion. `page_size=100` is the list paginator's max.

## Related

- [customer-location-at-start.md](customer-location-at-start.md) (KAN-54) — how the first GPS fix is obtained
- [retailer-store-location.md](retailer-store-location.md) (KAN-53) — where shop pins come from
- No delivery app ([ADR-001](../decisions/ADR-001-no-delivery-app.md))
