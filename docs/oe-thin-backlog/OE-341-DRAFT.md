---
id: OE-341
status: draft-not-minted
title: FE customer — optional delivery_charge on shop header
lane: FE (customer_ordereasy_njs)
suggested_base: "Customer sibling of #24 (do not edit orders/detail)"
---

# OE-341 DRAFT — FE customer — optional `delivery_charge` on shop header

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

`RetailerListSerializer` / profile already send `delivery_charge`. Customer shop home (`retailer/page.tsx`) uses the retailer object as `any` and shows pickup/delivery **flags**, but not the fee scalar. Shop **header** is the detail surface vs the retailer **list** map (KAN-69).

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `src/app/retailer/page.tsx` — header/meta only |
| Create | `src/app/retailer/shopDeliveryCharge.ts` + `shopDeliveryCharge.test.ts` |

Do **not** edit `ProductCard.tsx` (OE-316), `retailer/product/page.tsx` (OE-328), `cart/page.tsx` (OE-329), or `wishlist/page.tsx` (OE-332).

## Suggested title

`FE customer — optional delivery_charge on shop header`

## Lane

FE (`customer_ordereasy_njs`)

## Done-when / AC

1. Treat `delivery_charge` as optional `number | string | null`.
2. Present numeric ≠ 0 → muted header line. Missing/null/0 → hide; never invent ₹0.
3. No new API. Do not add free-delivery marketing unless that threshold is already rendered.
4. Helper tests: non-zero → text; 0/null → null.

## Out of scope

Order fees (OE-311 / OE-322); ProductCard brand; PDP brand; UPI / slots / timeline.

## Conflicts to avoid

- Do not restyle ProductCard or InfiniteProductGrid.
- Do not open customer order files.

## Vineet hard lock

Shop header display only. Keep UPI / slots / timeline / khata intact. Dummy / local only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

Customer app sibling of **#24**. Do not stack on `orders/detail/page.tsx`.

## QA pack

| Case | Expect |
|------|--------|
| Non-zero fee | Header shows fee |
| Zero/null | Hidden |
| ProductCard | Unchanged |

**Unit gate**

```bash
npm test -- shopDeliveryCharge
```
