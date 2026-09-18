---
id: OE-339
status: draft-not-minted
title: FE — optional unit on PurchaseReturnModal picker
lane: FE (retailer_ordereasy_njs)
suggested_base: "Retailer FE sibling of #56 tip 6bc80711 (not OE-304–309 list files)"
---

# OE-339 DRAFT — FE — optional `unit` on PurchaseReturnModal picker

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

Purchase-return picker rows (`get_invoice_items`) expose qty / price / batch_id but not `unit`. Product list/detail already have `unit`. FE `PurchaseReturnModal` cannot show “return 2 kg” without guessing. OE-331 owns **return-detail notes** on a different file.

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `src/components/dashboard/PurchaseReturnModal.tsx` — picker row label only |
| Create | `src/utils/purchaseReturnPickerUnit.ts` + `purchaseReturnPickerUnit.test.ts` |

Do **not** edit `purchases/return-detail/page.tsx` (OE-331), `purchases/page.tsx` (OE-309), `purchases/new/page.tsx` (OE-317), or `POSReturnModal.tsx` (OE-342).

## Suggested title

`FE — optional unit on PurchaseReturnModal picker`

## Lane

FE (`retailer_ordereasy_njs`)

## Done-when / AC

1. Picker item type includes `unit?: string | null`.
2. Trimmed non-empty → muted unit beside qty. Null/blank → hide; do not invent `pcs`.
3. Optional until BE OE-345 lands `unit` on `get_invoice_items`.
4. Return POST body unchanged.

## Out of scope

Purchase-return serializer (OE-344); return-detail page (OE-331 / OE-353); PI write; catalog/POS.

## Conflicts to avoid

- Not OE-331 return-detail notes.
- Not OE-323 purchase detail.
- Not OE-304 catalog/POS files.
- No `returns/views.py` until OE-320 SHIP (BE companion is OE-345).

## Vineet hard lock

Surgical modal display + helper tests. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` / pack write intact. Dummy / local only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

Retailer FE **#56** / `6bc80711` **sibling**. Do not stack on #55–#59 list-file PRs.

## QA pack

| Case | Expect |
|------|--------|
| Happy unit | Non-empty `unit` renders beside qty |
| Empty/null | No placeholder |
| Submit | Payload keys unchanged |
| Isolation | return-detail notes block not edited |

**Unit gate**

```bash
npm test -- purchaseReturnPickerUnit
```
