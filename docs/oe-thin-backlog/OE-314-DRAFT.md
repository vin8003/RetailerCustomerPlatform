---
id: OE-314
status: draft-not-minted
title: F follow-on — product identity on inventory-ledger rows
lane: BE
suggested_base: "BE #130 tip d022f37 sibling"
---

# OE-314 DRAFT — F follow-on — product identity on inventory-ledger rows

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

`GET /api/products/erp/inventory-ledger/` (OE-141) already returns log scalars and `batch_id`. Shop-wide `?reason=` rows have **no** `product_id` / `product_name` / `unit`, so a damage report cannot name the SKU without a second product GET. List/detail already have those identity fields.

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `products/api_erp_views.py` — `get_inventory_ledger` loop (~lines 878–889) only |
| Test | `products/tests/test_write_off_oe141.py` (`TestWriteOffLedgerFilter`) and/or `products/tests/test_inventory_ledger_product_identity_oe314.py` |

Do **not** edit `products/views.py` (OE-286 / OE-302). Do **not** edit `ProductSearchSerializer` or `PurchaseItemSerializer`.

## Suggested title

`F follow-on — product identity on inventory-ledger rows`

## Lane

BE

## Done-when / AC

1. Every ledger object includes `product_id`, `product_name`, `unit` from `log.product` (unit null/empty passthrough).
2. Existing keys unchanged: `id`, `log_type`, `batch_id`, `quantity_change`, `previous_quantity`, `new_quantity`, `reason`, `created_at`, `created_by`.
3. `?product_id=` and `?reason=` filters unchanged. Missing both still **400**.
4. Tenant B rows never appear on tenant A `?reason=` (existing test). Identity fields match the kept product.
5. Queryset uses `select_related('product')` (and keep `created_by`) — no N+1.

## Out of scope

Write-off POST; FE ledger page (OE-321 can show existing `batch_id` without this); POS; search Meta; inventing a ledger serializer class unless it stays in this file and is test-equivalent (prefer dict extend).

## Conflicts to avoid

- Not search Meta until OE-303 SHIP.
- Not `customers/serializers.py` (OE-305).
- Not POS `products/views.py` (OE-286 / OE-302).
- Not OE-304/306/307/308/309 FE sets.
- Not `PurchaseItemSerializer` (OE-310).

## Vineet hard lock

One ERP function + tests. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` write path intact (do not change `write_off_stock`). Dummy only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

BE **#130** sibling `d022f37`. Safe parallel with #139/#140/#141 (different files).

## QA pack

| Case | Expect |
|------|--------|
| Product-scoped GET | Row product_id / name / unit match the SKU |
| Reason-only GET | Each row names its own product; other shop omitted |
| Empty unit | Passthrough |
| Bad query | No product_id and no reason → 400 |
| Auth | 401 anonymous; 403 non-retailer |

**Unit gate**

```bash
pytest products/tests/test_write_off_oe141.py products/tests/test_inventory_ledger_product_identity_oe314.py -q --no-cov
pytest --no-cov
```
