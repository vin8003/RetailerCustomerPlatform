---
id: OE-317
status: draft-not-minted
title: FE — expiring-batches panel on reports
lane: FE (retailer_ordereasy_njs)
suggested_base: "retailer FE #54 sibling"
---

# OE-317 DRAFT — FE — expiring-batches panel on reports

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

OE-210 already ships `GET /api/products/erp/expiring-batches/` (product_name, batch_number, expiry_date, quantity, `is_expired`). Retailer **reports** page only loads daily sales summary — no expiry panel. Durable docs explicitly left FE dashboards out of OE-210. This is display of a landed READ.

## Isolated file slice

| Touch | Path (retailer_ordereasy_njs) |
|-------|-------------------------------|
| Modify | `src/app/dashboard/reports/page.tsx` (append panel; keep daily summary) |
| Create | `src/components/reports/ExpiringBatchesPanel.tsx` + `ExpiringBatchesPanel.test.tsx` |
| Helper | `src/utils/expiringBatchRow.ts` + `expiringBatchRow.test.ts` |

**Forbidden in this ticket:** `src/app/dashboard/pos/page.tsx`, `ProductTable.tsx`, `VirtualProductList.tsx`, `purchases/page.tsx`, `customers/page.tsx`, `OrderTable.tsx`, `suppliers/page.tsx`.

## Suggested title

`FE — expiring-batches panel on reports`

## Lane

FE (retailer_ordereasy_njs)

## Done-when / AC

1. Reports loads `GET /api/products/erp/expiring-batches/` (default N=30; no `days` query required).
2. Each row shows `product_name`, `batch_number`, `expiry_date`, `quantity`. When `is_expired === true`, muted Expired badge; false/absent → no badge.
3. `[]` → empty state copy, not fake SKUs.
4. 401/403 → toast / hide panel (do not crash the daily summary).
5. No write-off button, no notify, no MIS charts invent.

## Out of scope

Full F-0125; OE-141 write-off UI (#42); catalog/POS badges (OE-304); purchase list (OE-309); BE changes.

## Conflicts to avoid

- Not OE-304/306/307/308/309 FE file sets.
- Not POS views / search Meta / customers serializers.
- Not OE-286 POS unit work.

## Vineet hard lock

Reports page + new reports components only. Do not break POS checkout, khata, UPI, slots. Dummy / preview only. **No merge. Do not mark Done.** Never `retailer.ordereasy.win`.

## Suggested base tip

Retailer FE **#54** sibling (OE-297 tip). Isolated from #55–#58 file sets.

## QA pack

| Case | Expect |
|------|--------|
| API returns 2 batches | Two rows; names/dates visible |
| is_expired true | Expired badge |
| is_expired false | No badge |
| Empty list | Empty state |
| 403 | Daily summary still renders |

**Unit gate**

```bash
npm test -- expiringBatchRow ExpiringBatches
# match retailer_ordereasy_njs existing test script
```
