---
id: OE-313
status: draft-not-minted
title: F follow-on — unit on sales-return items
lane: BE
suggested_base: "BE #130 tip d022f37 (sibling, not stacked on #139/#140/#141)"
---

# OE-313 DRAFT — F follow-on — `unit` on sales-return items

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

`OrderItemSerializer` already exposes `product_unit`. Product list/detail already expose `unit`. `SalesReturnItemSerializer` only has `product_name` + batch number — the return GET/create read omits unit, so FE cannot show “2 kg returned” without guessing.

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `returns/serializers.py` — `SalesReturnItemSerializer` only |
| Optional queryset | `returns/views.py` **only** if `SalesReturnViewSet.get_queryset` needs `prefetch_related('items__product')` / `select_related` — skip if already present |
| Test | `returns/tests/test_sales_return_item_unit_oe313.py` (prefer new) + keep `returns/tests/test_sales_returns.py` green |

Do **not** edit `PurchaseReturnItemSerializer` (OE-325), `search_order` dict (OE-323), `products/views.py`, or `ProductSearchSerializer`.

## Suggested title

`F follow-on — unit on sales-return items`

## Lane

BE (`RetailerCustomerPlatform`)

## Done-when / AC

1. Sales-return `items[]` includes `unit` equal to `product.unit` for that SKU.
2. Null/empty `unit` stays null/empty — do not invent `piece` / `pcs`.
3. 401 unauthenticated. Other-shop returns are not visible (existing queryset).
4. No extra query per item: `source='product.unit'` + `select_related`/`prefetch` if the create/list queryset does not already join product.
5. Existing sales-return stock and loyalty reversal behavior unchanged.

## Out of scope

Purchase-return serializer; return picker views; POS no_page; search Meta; FE POSReturnModal; write-policy / refund math.

## Conflicts to avoid

- Do **not** propose search `ProductSearchSerializer` Meta until OE-303 SHIP (OE-312 already queues `is_in_stock`).
- Do **not** collide `customers/serializers.py` with OE-305.
- Do **not** collide POS views with OE-286 / OE-302.
- Do **not** collide OE-304/306/307/308/309 FE file sets.

## Vineet hard lock

Surgical `SalesReturnItemSerializer` + tests. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` / pack write intact. Dummy / local pytest only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

BE **#130** / `d022f37` **sibling** (OE-300 PASS). Do not stack on #139 (POS views), #140 (search Meta), or #141 (customers/serializers).

## QA pack

| Case | Expect |
|------|--------|
| Happy unit echo | GET after create: item.unit == product.unit |
| Empty unit | Product.unit `""` or null → payload empty/null, key present |
| Auth missing | 401 |
| Other retailer | Cannot read shop A return |
| Non-regression | `test_sales_return_proportional_points_reversal` still 201 + stock math |

**Unit gate**

```bash
pytest returns/tests/test_sales_returns.py returns/tests/test_sales_return_item_unit_oe313.py -q --no-cov
pytest --no-cov
```
