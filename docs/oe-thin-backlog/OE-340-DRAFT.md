---
id: OE-340
status: draft-not-minted
title: FE — read-only saleable_quantity hint on ProductForm
lane: FE (retailer_ordereasy_njs)
suggested_base: "Retailer FE sibling of #56 / #54 (not ProductTable / pos/page)"
---

# OE-340 DRAFT — FE — read-only `saleable_quantity` hint on ProductForm

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

OE-132 already echoes `saleable_quantity` on retailer product reads (pack/parent math). Catalog/POS **list** stock is OE-288. Product **edit** form still shows only raw `quantity`, so staff cannot see saleable vs on-hand without leaving the form.

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `src/components/products/ProductForm.tsx` — read-only hint near Stock Quantity |
| Create | `src/utils/saleableQuantityHint.ts` + `saleableQuantityHint.test.ts` |

Do **not** edit `ProductTable.tsx`, `VirtualProductList.tsx`, or `pos/page.tsx` (OE-304 / OE-288).

## Suggested title

`FE — read-only saleable_quantity hint on ProductForm`

## Lane

FE (`retailer_ordereasy_njs`)

## Done-when / AC

1. Loaded product may include `saleable_quantity?: number | string | null`.
2. Show muted `Saleable: N` only when the value is finite **and** differs from the editable quantity. Equal / missing / null → hide.
3. Do **not** append `saleable_quantity` on create/update FormData.
4. Helper unit tests cover differ / equal / null.

## Out of scope

POS/catalog stock column (OE-288); pack write; `inventory.adjust`; BE.

## Conflicts to avoid

- Not OE-304 availability badges.
- Not OE-318 ledger page.
- Add-product path (no saleable yet) must stay hidden.

## Vineet hard lock

Read-only hint only. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` / pack write intact. Dummy / local only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

Retailer FE sibling of **#56** / **#54**. Not stacked on catalog badge PRs #50–#55.

## QA pack

| Case | Expect |
|------|--------|
| saleable ≠ quantity | Hint visible |
| saleable = quantity | Hidden |
| Add product | No hint |
| Save | No `saleable_quantity` in payload |

**Unit gate**

```bash
npm test -- saleableQuantityHint
```
