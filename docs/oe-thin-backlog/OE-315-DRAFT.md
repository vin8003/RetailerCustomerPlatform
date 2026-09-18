---
id: OE-315
status: draft-not-minted
title: F follow-on — brand_name on cart items
lane: BE
suggested_base: "BE #130 tip d022f37 sibling"
---

# OE-315 DRAFT — F follow-on — `brand_name` on cart items

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

Product list/detail/search already expose `brand_name` (OE-287). `CartItemSerializer` already echoes `product_name`, `product_unit`, prices, and `is_available`, but not brand. Customer cart UI cannot show brand without a second product fetch.

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `cart/serializers.py` — `CartItemSerializer` fields + `brand_name = CharField(source='product.brand.name', …)` |
| Optional | Cart GET queryset `select_related('product__brand')` in `cart/views.py` **only if** needed to avoid N+1 |
| Test | `cart/tests/test_cart_item_brand_oe315.py` + `cart/tests/test_views.py` |

Do **not** add `barcode` here (OE-326). Do **not** touch `customers/serializers.py` (wishlist / OE-305).

## Suggested title

`F follow-on — brand_name on cart items`

## Lane

BE

## Done-when / AC

1. Cart item includes `brand_name` matching product list/detail for the same SKU.
2. No brand → `null` (allow_null). Do not invent from `product_name`.
3. Customer GET cart 200; retailer 403; anonymous 401.
4. Add-to-cart / qty validation unchanged (`is_available` / saleable checks stay).
5. No N+1: one brand join, not `Brand.objects.get` per row.

## Out of scope

Cart write; barcode (OE-326); wishlist scalars (OE-305 file); search Meta; retailer POS.

## Conflicts to avoid

- Not search Meta until OE-303 SHIP.
- Not `customers/serializers.py` (OE-305).
- Not POS views (OE-286 / OE-302).
- Not OE-304/306/307/308/309 FE sets.

## Vineet hard lock

Cart serializer (+ optional select_related) + tests. Do not break checkout, khata, UPI, slots. Dummy only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

BE **#130** sibling `d022f37`. Parallel-safe vs #139/#140/#141.

## QA pack

| Case | Expect |
|------|--------|
| Branded SKU | cart item.brand_name == list brand_name |
| Unbranded SKU | brand_name is null |
| Auth | 401 / retailer 403 |
| Non-regression | `test_add_to_cart_success` still 201 |

**Unit gate**

```bash
pytest cart/tests/test_views.py cart/tests/test_cart_item_brand_oe315.py -q --no-cov
pytest --no-cov
```
