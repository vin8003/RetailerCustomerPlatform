---
id: KAN-11
title: Retailer Web — Mobile Friendly
knowledge_class: mixed
owning_repo: retailer_ordereasy_njs
durable_docs:
  - docs/requirements/retailer-web-mobile.md
jira: https://vin8003.atlassian.net/browse/KAN-11
confluence: https://vin8003.atlassian.net/wiki/spaces/KAN/pages/98346/KAN-11+Retailer+Web+Mobile+Friendly
gitbook: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/open-jira-ticket-docs/kan-11-retailer-web-mobile-friendly
---

# KAN-11 Retailer Web — Mobile Friendly

Work snapshot copied from Confluence (retained). Jira is status. Durable UX rules: [retailer-web-mobile.md](../requirements/retailer-web-mobile.md).

**PR (historical):** `feature/KAN-11-mobile-friendly` on `retailer_ordereasy_njs`.

## Snapshot

The retailer portal is a Next.js dashboard for products, orders, customers, offers, and POS. Mobile work included:

### Shell and layout

- `useIsMobile.ts` (`< 768px`)
- Viewport metadata to block iOS input-focus auto-zoom
- Mobile header: shop name + initial avatar from profile API
- Bottom nav: POS as a core tab; Catalog / Purchases / Suppliers in the drawer

### Responsive fallbacks

- `OrderCardListMobile` vs desktop orders table
- `ProductCardListMobile` vs desktop catalog table (thumbnails, category, low-stock, actions)

### POS

- Tablet: vertical stack (search top, sticky cart)
- Phone: “Desktop recommended” overlay
- Compact cart rows; payment options in a grid

### Polish

- Dashboard stats `grid-cols-2` on mobile
- Compact product rows; horizontal-scroll status filters
- Category `grid-cols-2`; operating hours aligned on mobile

### Lookup

- Space-separated fuzzy match (POS, purchases, selectors)
- Enter adds barcode match, or the single fuzzy match
- `no_page=true` on purchases/lookup so client search sees the full catalog

Verification noted on the Confluence page: `tsc --noEmit` clean, ESLint, production build.
