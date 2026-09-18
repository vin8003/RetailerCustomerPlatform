---
id: OE-342
status: draft-not-minted
title: FE — optional unit on POSReturnModal picker
lane: FE (retailer_ordereasy_njs)
suggested_base: "Retailer FE sibling of #56; after OE-327 SHIP if that PR opened POSReturnModal.tsx"
---

# OE-342 DRAFT — FE — optional `unit` on POSReturnModal picker

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

`search_order` picker items (OE-320) will echo `unit`. `POSReturnModal` `OrderItem` has qty / `unit_price` / `batch_id` but no unit label, so POS cannot show “return 1.5 kg”.

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `src/components/pos/POSReturnModal.tsx` — picker/process row label |
| Create | `src/utils/posReturnPickerUnit.ts` + `posReturnPickerUnit.test.ts` |

Do **not** edit `pos/page.tsx` (OE-304). Do **not** edit `PurchaseReturnModal.tsx` (OE-339).

## Gate vs OE-327

OE-327 is sales-return **detail notes**. If that work opened `POSReturnModal.tsx`, **wait for OE-327 SHIP**. If 327 added a new detail route, this ticket may start now as a sibling.

## Suggested title

`FE — optional unit on POSReturnModal picker`

## Lane

FE (`retailer_ordereasy_njs`)

## Done-when / AC

1. `OrderItem.unit?: string | null`.
2. Trimmed non-empty → muted unit beside qty. Blank → hide; no `pcs` invent.
3. Hidden until OE-320 payload includes `unit`.
4. Search / process / POST body unchanged.

## Out of scope

OE-313 sales-return serializer; OE-327 notes; purchase modal; POS catalog tiles.

## Conflicts to avoid

- OE-327 same-file collision.
- OE-304 `pos/page.tsx`.
- No `returns/views.py` edits (OE-320 lock).

## Vineet hard lock

Modal display only. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` intact. Dummy / local only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

Retailer FE **#56** sibling, or stack on the OE-327 branch if it owns this file.

## QA pack

| Case | Expect |
|------|--------|
| Unit present | Shown beside qty |
| Unit blank | Hidden |
| Submit | Payload unchanged |

**Unit gate**

```bash
npm test -- posReturnPickerUnit
```
