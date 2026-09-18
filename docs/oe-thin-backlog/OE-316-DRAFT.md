---
id: OE-316
status: draft-not-minted
title: FE customer — optional brand_name on ProductCard
lane: FE (customer_ordereasy_njs)
suggested_base: "customer_ordereasy_njs tip (sibling of #22/#23); not retailer #54 catalog files"
---

# OE-316 DRAFT — FE customer — optional `brand_name` on ProductCard

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

Public / shop product **list** already sends top-level `brand_name` (`ProductListSerializer`). Customer `ProductCard` types only `name`, `price`, `mrp`, `unit`, offer text — brand is dropped. Same optional-scalar pattern as retailer OE-292, but on the **customer** card (retailer catalog files are locked by OE-304).

## Isolated file slice

| Touch | Path (customer_ordereasy_njs) |
|-------|-------------------------------|
| Modify | `src/app/components/ProductCard.tsx` |
| Optional CSS | `src/app/components/ProductCard.module.css` |
| Helper + test | `src/app/components/productBrandLabel.ts` + `productBrandLabel.test.ts` |
| Wire | `InfiniteProductGrid.tsx` / `LazyProductLane.tsx` **only** if they strip unknown fields — pass `brand_name` through, no layout rewrite |

Do **not** edit retailer `ProductTable.tsx` / `pos/page.tsx` (OE-304). Do **not** edit customer `orders/detail/page.tsx` (OE-311).

## Suggested title

`FE customer — optional brand_name on ProductCard`

## Lane

FE (customer_ordereasy_njs)

## Done-when / AC

1. Product type includes `brand_name?: string | null`.
2. Trimmed non-empty → muted secondary line under the title. Null/blank/absent → render nothing (no “Unknown brand”).
3. No new API call. No invent from nested `brand` if top-level missing (prefer top-level only).
4. Helper unit tests: present / blank / whitespace.

## Out of scope

Featured/seasonal badges (OE-319 — same file, run after this). Retailer catalog. PDP rewrite. BE. Cart brand (needs OE-315 first if cart page is in a later ticket).

## Conflicts to avoid

- Not retailer OE-304/306/307/308/309 file sets.
- Not customer order detail (OE-311).
- Do not parallel another ProductCard ticket (OE-319 waits).
- Not search Meta / POS views / customers serializers.

## Vineet hard lock

Customer ProductCard display only. Do not break add-to-cart, wishlist, fulfillment slots, UPI. Dummy / local tests only. **No merge. Do not mark Done.** Never `customer.ordereasy.win`.

## Suggested base tip

Customer app current integration tip (sibling of customer PRs #22 / #23). Not retailer FE #54 product files.

## QA pack

| Case | Expect |
|------|--------|
| brand_name "Amul" | Muted line visible |
| brand_name null / "" / "  " | No extra line |
| Offer + % OFF badges | Still show |
| Click card | Still navigates to PDP |

**Unit gate** (use the customer repo’s existing runner):

```bash
npm test -- productBrandLabel
# if the repo uses jest/vitest scripts, keep that script; do not invent a new toolchain
```
