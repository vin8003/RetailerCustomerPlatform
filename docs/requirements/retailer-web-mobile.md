# Retailer web is mobile-friendly

- **Ticket:** [KAN-11](https://vin8003.atlassian.net/browse/KAN-11) · [snapshot](../tickets/KAN-11.md)
- **App:** `retailer_ordereasy_njs`

Durable UX constraints (implementation details stay in the snapshot):

- Viewport `< 768px` is the mobile breakpoint (`useIsMobile`).
- Block iOS input-focus auto-zoom via viewport metadata.
- Orders and product catalog use **card lists** on mobile, tables on desktop.
- POS on phone: “Desktop recommended” overlay; tablet: stacked search + sticky cart.
- Product lookup is space-separated fuzzy match; Enter adds barcode or the single fuzzy match.
- Purchases/lookup may request `no_page=true` so client-side search sees the full catalog.

Full component list and verification log: [../tickets/KAN-11.md](../tickets/KAN-11.md).
