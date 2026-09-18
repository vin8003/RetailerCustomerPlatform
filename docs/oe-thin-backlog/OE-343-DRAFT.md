---
id: OE-343
status: draft-not-minted
title: F follow-on — brand_name on wishlist items
lane: BE
suggested_base: "After OE-305 SHIP; then BE #130 sibling (not #141 while open)"
---

# OE-343 DRAFT — F follow-on — `brand_name` on wishlist items

Mint-ready thin. **Not a Jira issue until minted.** Dummy only. No merge. No Done. Never `*.ordereasy.win`.

## Why thin

Product list/detail already expose `brand_name`. `CustomerWishlistSerializer` only has name / price / image / retailer. OE-332 is the **FE** display (optional keys). This ticket is the BE echo so the FE line can appear.

## Isolated file slice

| Touch | Path |
|-------|------|
| Modify | `customers/serializers.py` — `CustomerWishlistSerializer` only |
| Optional queryset | wishlist view `select_related('product__brand')` if missing |
| Test | `customers/tests/test_wishlist_brand_oe338.py` |

Do **not** edit `RetailerCustomerListSerializer` (OE-305). Do **not** edit cart serializers (OE-314).

## Suggested title

`F follow-on — brand_name on wishlist items`

## Lane

BE (`RetailerCustomerPlatform`)

## Done-when / AC

1. Wishlist JSON includes `brand_name` equal to product list/detail for that SKU.
2. Null brand → `null`. Do not invent from product name.
3. 401 unauthenticated. Customer-only.
4. No per-row brand query.

## Out of scope

OE-332 FE; OE-305 list scalars; search Meta; cart `brand_name` (OE-314).

## Conflicts to avoid

- **No `customers/serializers.py` until OE-305 SHIP.**
- Not `cart/serializers.py` (OE-314).
- Not `ProductSearchSerializer` Meta (OE-312).

## Vineet hard lock

Surgical wishlist field + tests. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` / pack write intact. Dummy / local pytest only. **No merge. Do not mark Done.** Never `*.ordereasy.win`.

## Suggested base tip

**After OE-305 SHIP**, then BE **#130** / `d022f37` sibling. Do not stack on #141 while open.

## QA pack

| Case | Expect |
|------|--------|
| Happy | `brand_name` matches product list |
| Null brand | `null` |
| Auth missing | 401 |

**Unit gate**

```bash
pytest customers/tests/test_wishlist_brand_oe338.py customers/tests/test_serializers.py -q --no-cov
pytest --no-cov
```
