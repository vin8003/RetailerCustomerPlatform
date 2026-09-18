# OrderEasy thin backlog (scout round 2, 2026-09-18)

Prioritized mint-ready thins so CA slots are not blocked by in-flight search-Meta / cart / returns / FE list-detail locks. **Docs only.** Keys `OE-339`–`OE-353` are **draft labels** for minting — they are not Jira issues yet (highest minted at this scout: **OE-338**).

Round 1 (PR **#143**) drafted `OE-313`–`OE-327`; those numbers were then minted with remapped titles. A later wave minted **OE-323–338** as FE list/detail thins. See [MINTED-REMAP.md](MINTED-REMAP.md). **Do not re-mint 301–338.**

Scout bases: docs PR **#143** tip `cd43729`; BE PR **#130** tip `d022f37` (OE-300 PASS). Do not invent layers, epics, offline, notify, exchange, PIN, OE-102 / #103 rebuild, or parallel engines.

## Vineet hard lock (every ticket)

Copy this block into each minted Jira card:

- Surgical slice only. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` / pack **write** intact.
- **Dummy / local only.** Never hit `*.ordereasy.win`.
- **No merge.** **Do not mark Done.** Leave status Dev Ready / In Review.
- No new services, no N+1, no write-path invent, no GST / HSN rebuild (KAN-57 / OE-102).

## Isolation — do not collide

| Hot surface | Owner now | Rule |
|-------------|-----------|------|
| `products/serializers.py` `ProductSearchSerializer` Meta | **OE-312** (#142) after OE-303 | **No new search Meta until OE-312 SHIP.** |
| `products/serializers.py` `PurchaseItemSerializer` | **OE-310** (#144) | No PI line fields until OE-310 SHIP. Then OE-349 (`barcode`) only. |
| `cart/serializers.py` | **OE-314** (#146) | **No cart serializers until OE-314 SHIP.** Then OE-348 (`barcode`) only. |
| `returns/serializers.py` | **OE-313** (#145) | **No returns/serializers until OE-313 SHIP.** Then OE-344 (purchase-return `unit`) only. |
| `returns/views.py` | **OE-320** | **No returns/views until OE-320 SHIP.** Then OE-345 (`get_invoice_items` `unit`) only. |
| `products/api_erp_views.py` ledger | **OE-315** (#147) | No ledger dict keys until OE-315 SHIP. Then OE-350 (`unit`) only. |
| `customers/serializers.py` | **OE-305** (#141) | No wishlist/list/detail customer scalars until OE-305 SHIP. Then OE-343 (wishlist `brand_name`) only. |
| `orders/serializers.py` | **OE-301** (#138) | No order item/list Meta until OE-301 SHIP. Then OE-352 (`brand_name` on `OrderItemSerializer`) only. |
| `products/views.py` POS `?no_page=true` | **OE-286** + **OE-302** (#139) | Do not add POS row keys. |
| Retailer FE catalog + POS tiles | **OE-304** (#55) + OE-288/289/292/296/297 + **OE-334** POS cart brand | Do not touch `ProductTable.tsx`, `VirtualProductList.tsx`, `pos/page.tsx`. |
| Retailer FE customers **list** | **OE-306** (#56) | `customers/page.tsx` locked. |
| Retailer FE customers **details** | **OE-321** | `customers/details/page.tsx` locked. Khata **list** notes = OE-333. |
| Retailer FE orders **list** | **OE-307** (#57) | `OrderTable.tsx` locked. |
| Retailer FE orders **details** | **OE-325** notes + **OE-330** phone | `orders/details/page.tsx` locked. |
| Retailer FE suppliers **list** | **OE-308** (#58) + **OE-337** email | `suppliers/page.tsx` locked. |
| Retailer FE suppliers **detail** | **OE-324** | Do not invent a second supplier-detail slice. Ledger page is adjacent — do not steal it. |
| Retailer FE purchases **list** | **OE-309** (#59) | `purchases/page.tsx` locked. |
| Retailer FE purchases **NEW** | **OE-317** | `purchases/new/page.tsx` locked. |
| Retailer FE purchases **detail** | **OE-323** | Do not treat `purchases/edit` as free if 323 lands there. |
| Retailer FE purchase-**return** detail | **OE-331** | `purchases/return-detail/page.tsx` locked (notes). Unit on that page = OE-353 **after 331 SHIP**. |
| Retailer FE inventory ledger | **OE-318** | `products/ledger/page.tsx` locked. Identity display = OE-351 after 318+315 SHIP. |
| Retailer FE reports | **OE-319** | `reports/page.tsx` locked. |
| Retailer FE write-off **list** | **OE-326** | Write-off list reason locked. |
| Retailer FE sales-return **detail** | **OE-327** | If 327 opens `POSReturnModal.tsx`, wait — see OE-342. |
| Customer FE order **detail** | **OE-311** (#24) + **OE-335** notes | `orders/detail/page.tsx` locked. |
| Customer FE order **list** | **OE-322** | `orders/page.tsx` locked. |
| Customer FE ProductCard | **OE-316** | `ProductCard.tsx` locked. Featured = OE-346 after 316 SHIP. |
| Customer FE PDP brand | **OE-328** | `retailer/product/page.tsx` locked. Featured = OE-347 after 328 SHIP. |
| Customer FE cart brand | **OE-329** | `cart/page.tsx` locked until 329 SHIP. |
| Customer FE wishlist brand | **OE-332** | `wishlist/page.tsx` locked (FE). BE companion = OE-343 after 305. |
| Customer FE product **list** unit | **OE-338** | Not ProductCard — `InfiniteProductGrid` / shop products list helpers locked. |
| Retailer FE sales-return **list** | **OE-336** | Sales-return list notes locked. |

## Already minted (do not re-mint)

| Key | Lane | Status (scout) | Why skip |
|-----|------|----------------|----------|
| OE-301 | BE | In Review #138 | `delivery_fee` / `discount_amount` on order list |
| OE-302 | BE | In Review #139 | POS no_page availability bools |
| OE-303 | BE | In Review #140 | search `is_available` |
| OE-304 | FE retailer | In Review #55 | catalog/POS unavailable / OOS badges |
| OE-305 | BE | In Review #141 | customer list scalars |
| OE-306 | FE retailer | In Review #56 | customer list display |
| OE-307 | FE retailer | In Review #57 | order list fee lines |
| OE-308 | FE retailer | In Review #58 | supplier list GST / terms |
| OE-309 | FE retailer | In Review #59 | purchase **list** notes |
| OE-310 | BE | In Review #144 | PI line `unit` |
| OE-311 | FE customer | Dev In Progress #24 | order **detail** fees |
| OE-312 | BE | In Review #142 | search `is_in_stock` — **after OE-303 SHIP only** |
| OE-313 | BE | Dev In Progress #145 | sales-return item `unit` |
| OE-314 | BE | Dev In Progress #146 | cart `brand_name` |
| OE-315 | BE | Dev In Progress #147 | ledger product identity |
| OE-316 | FE customer | Dev In Progress | ProductCard `brand_name` |
| OE-317 | FE retailer | Dev In Progress | purchase NEW last-supplier-costs |
| OE-318 | FE retailer | Dev In Progress | ledger `batch_id` |
| OE-319 | FE retailer | Dev In Progress | reports expiring-batches |
| OE-320 | BE | Dev In Progress | sales-return `search_order` `unit` |
| OE-321 | FE retailer | Dev In Progress | customer **details** notes |
| OE-322 | FE customer | Dev In Progress | customer order **list** fees |
| OE-323 | FE retailer | Dev In Progress | purchase **detail** notes |
| OE-324 | FE retailer | Dev In Progress | supplier **detail** GST / terms |
| OE-325 | FE retailer | Dev In Progress | retailer order **detail** notes |
| OE-326 | FE retailer | Dev In Progress | write-off **list** reason |
| OE-327 | FE retailer | Dev In Progress | sales-return **detail** notes |
| OE-328 | FE customer | Dev In Progress | PDP `brand_name` |
| OE-329 | FE customer | Dev In Progress | cart line `brand_name` |
| OE-330 | FE retailer | Dev In Progress | order detail customer **phone** |
| OE-331 | FE retailer | Dev In Progress | purchase-return **detail** notes |
| OE-332 | FE customer | Need Clarity / flying | wishlist `brand_name` display |
| OE-333 | FE retailer | Dev In Progress | khata ledger **list** notes |
| OE-334 | FE retailer | Dev In Progress | POS **cart line** `brand_name` |
| OE-335 | FE customer | Dev In Progress | order **detail** notes |
| OE-336 | FE retailer | Dev In Progress | sales-return **list** notes |
| OE-337 | FE retailer | Dev In Progress | supplier **list** email |
| OE-338 | FE customer | Dev In Progress | product **list** `unit` (not ProductCard) |

## Priority index

| P | Draft key | Title | Lane | Start now? |
|---|-----------|-------|------|------------|
| 1 | OE-339 | FE — optional `unit` on PurchaseReturnModal picker | FE (retailer_ordereasy_njs) | Yes — modal file, not OE-331 detail |
| 2 | OE-340 | FE — read-only `saleable_quantity` hint on ProductForm | FE (retailer_ordereasy_njs) | Yes — catalog **detail**, not OE-304 list |
| 3 | OE-341 | FE customer — optional `delivery_charge` on shop header | FE (customer_ordereasy_njs) | Yes — `retailer/page.tsx` header only |
| 4 | OE-342 | FE — optional `unit` on POSReturnModal picker | FE (retailer_ordereasy_njs) | Yes **if** OE-327 did not open this file; else after 327 SHIP |
| 5 | OE-343 | F follow-on — `brand_name` on wishlist items | BE | After **OE-305 SHIP** |
| 6 | OE-344 | F follow-on — `unit` on purchase-return items | BE | After **OE-313 SHIP** |
| 7 | OE-345 | F follow-on — `unit` on purchase-return `get_invoice_items` | BE | After **OE-320 SHIP** |
| 8 | OE-346 | FE customer — optional featured / seasonal on ProductCard | FE (customer_ordereasy_njs) | After **OE-316 SHIP** |
| 9 | OE-347 | FE customer — optional featured / seasonal on PDP | FE (customer_ordereasy_njs) | After **OE-328 SHIP** |
| 10 | OE-348 | F follow-on — `barcode` on cart items | BE | After **OE-314 SHIP** |
| 11 | OE-349 | F follow-on — `barcode` on purchase invoice line items | BE | After **OE-310 SHIP** (not parallel OE-312) |
| 12 | OE-350 | F follow-on — `unit` on inventory-ledger rows | BE | After **OE-315 SHIP** |
| 13 | OE-351 | FE — optional product identity on inventory ledger | FE (retailer_ordereasy_njs) | After **OE-318** and **OE-315** SHIP |
| 14 | OE-352 | F follow-on — `brand_name` on order line items | BE | After **OE-301 SHIP** |
| 15 | OE-353 | FE — optional `unit` on purchase return-detail lines | FE (retailer_ordereasy_njs) | After **OE-331 SHIP** (same page) |

---

## OE-339 — FE — optional `unit` on PurchaseReturnModal picker

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/components/dashboard/PurchaseReturnModal.tsx` plus `src/utils/purchaseReturnPickerUnit.ts` + `purchaseReturnPickerUnit.test.ts`. **Not** `purchases/return-detail/page.tsx` (OE-331). **Not** `purchases/page.tsx` (OE-309). **Not** `purchases/new/page.tsx` (OE-317).
- **Suggested base tip:** Retailer FE sibling of **#56** tip `6bc80711` / current #54 family. Do not stack on OE-304–309 list PRs.
- **Done-when / AC:**
  1. Picker row type: `unit?: string | null`.
  2. When trimmed non-empty, show muted unit next to qty (e.g. `2 kg`). Missing/null/blank → no invent / no `pcs`.
  3. BE: OE-345 will add `unit` on `get_invoice_items`. Until then optional key stays hidden.
  4. Helper unit tests (present → text; blank → null).
- **Out of scope:** Return write; purchase list notes (OE-309); return-detail notes (OE-331); POSReturnModal (OE-342).
- **Conflicts to avoid:** OE-331 return-detail page. OE-323 purchase detail. OE-304 POS/catalog.
- **Vineet hard lock:** Modal display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Present unit renders beside qty
  - Absent/blank hidden
  - Existing return submit payload unchanged (no extra write keys)
  - **Unit gate:** retailer `npm test -- purchaseReturnPickerUnit` (or repo equivalent)

---

## OE-340 — FE — read-only `saleable_quantity` hint on ProductForm

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/components/products/ProductForm.tsx` plus `src/utils/saleableQuantityHint.ts` + test. **Not** `ProductTable.tsx` / `pos/page.tsx` (OE-304 / OE-288).
- **Suggested base tip:** Retailer FE sibling of #56 / #54. Not catalog badge PRs.
- **Done-when / AC:**
  1. Types: `saleable_quantity?: number | string | null` on the loaded product (edit path).
  2. When the value is a finite number **and** differs from the editable `quantity` field, show a muted read-only line `Saleable: N`. Equal / missing / null → hide (no invent).
  3. Do **not** write `saleable_quantity` on submit. Do not change quantity / batch / `inventory.adjust` gates.
  4. Helper tests: differ → label; equal/null → null.
- **Out of scope:** Catalog/POS stock column (OE-288); pack write; OE-132 BE (already shipped on tip).
- **Conflicts to avoid:** OE-304 catalog/POS files. Product add vs edit share this form — keep add (no saleable yet) hidden.
- **Vineet hard lock:** Read-only hint only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Edit SKU with saleable ≠ quantity shows hint
  - Equal/absent hidden
  - Save payload has no `saleable_quantity`
  - **Unit gate:** `npm test -- saleableQuantityHint`

---

## OE-341 — FE customer — optional `delivery_charge` on shop header

- **Lane:** FE (customer_ordereasy_njs)
- **Isolated file slice:** `src/app/retailer/page.tsx` header/meta only plus `src/app/retailer/shopDeliveryCharge.ts` + test. Pass-through only if the shop fetch already returns the field. **Not** `ProductCard.tsx` (OE-316). **Not** `retailer/product/page.tsx` (OE-328).
- **Suggested base tip:** Customer sibling of #24 — do **not** edit `orders/detail/page.tsx`.
- **Done-when / AC:**
  1. Types: `delivery_charge?: number | string | null` (and optionally `minimum_order_amount?` already on list).
  2. When `delivery_charge` is present and numeric ≠ 0, muted line on the shop header (e.g. delivery fee). Missing/null/0 → hide. Do not invent free-delivery copy unless `free_delivery_threshold` is already shown.
  3. `RetailerListSerializer` / profile already expose `delivery_charge`. No BE.
  4. Helper tests: non-zero → text; 0/null → null.
- **Out of scope:** ProductCard brand (OE-316); PDP (OE-328); cart (OE-329); UPI / slots.
- **Conflicts to avoid:** Do not restyle ProductCard or InfiniteProductGrid. Touch header markup + helper only.
- **Vineet hard lock:** Shop header display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Non-zero fee visible
  - Zero/null hidden
  - Featured lane / ProductCard unchanged
  - **Unit gate:** customer helper tests for `shopDeliveryCharge`

---

## OE-342 — FE — optional `unit` on POSReturnModal picker

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/components/pos/POSReturnModal.tsx` plus `src/utils/posReturnPickerUnit.ts` + test. **Not** `pos/page.tsx` (OE-304).
- **Suggested base tip:** Retailer FE sibling of #56. **Gate:** if OE-327 already opened `POSReturnModal.tsx`, stack **after OE-327 SHIP**. If 327 created a new sales-return **detail route**, start now as a sibling.
- **Done-when / AC:**
  1. `OrderItem` type: `unit?: string | null`.
  2. Trimmed non-empty → muted unit beside qty. Blank/null → hide; no `pcs` invent.
  3. BE: OE-320 adds `unit` on `search_order`. Until SHIP, optional key stays hidden.
  4. Submit payload unchanged.
- **Out of scope:** Sales-return **detail notes** (OE-327); sales-return serializer (OE-313); purchase modal (OE-339).
- **Conflicts to avoid:** OE-327 same-file collision. OE-304 POS page.
- **Vineet hard lock:** Modal display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Unit present / hidden
  - Search + process steps still work
  - **Unit gate:** `npm test -- posReturnPickerUnit`

---

## OE-343 — F follow-on — `brand_name` on wishlist items

- **Lane:** BE
- **Isolated file slice:** `customers/serializers.py` (`CustomerWishlistSerializer` only). Tests: `customers/tests/test_wishlist_brand_oe338.py`.
- **Suggested base tip:** **After OE-305 SHIP.** Then sibling of #130 — do not stack on #141 while it is open.
- **Done-when / AC:**
  1. Wishlist row includes `brand_name` matching product list/detail (`product.brand.name` or null).
  2. Null brand → `null`. No invent from product name.
  3. Auth: customer only; 401 anonymous. Tenancy unchanged.
  4. `select_related('product__brand')` on the wishlist queryset if missing — no per-row query.
- **Out of scope:** Wishlist FE (OE-332). Cart serializers (OE-314). Customer list scalars (OE-305).
- **Conflicts to avoid:** Parallel OE-305 on `customers/serializers.py`.
- **Vineet hard lock:** One serializer field + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Branded SKU echoes list `brand_name`
  - Null brand → null
  - Unauthenticated 401
  - **Unit gate:** `pytest customers/tests/test_wishlist_brand_oe338.py customers/tests/test_serializers.py -q --no-cov` then `pytest --no-cov`

---

## OE-344 — F follow-on — `unit` on purchase-return items

- **Lane:** BE
- **Isolated file slice:** `returns/serializers.py` (`PurchaseReturnItemSerializer` only). Tests: `returns/tests/test_purchase_return_item_unit_oe339.py`.
- **Suggested base tip:** **After OE-313 SHIP** (same file — do not parallel).
- **Done-when / AC:**
  1. Purchase-return `items[]` includes `unit` from `product.unit` (null/empty passthrough).
  2. Auth/tenancy unchanged. READ echo only.
  3. No N+1 (`source='product.unit'` + existing prefetch).
- **Out of scope:** Sales-return serializer (OE-313); picker views (OE-345); OE-310 PI serializer.
- **Conflicts to avoid:** Parallel OE-313 on `returns/serializers.py`.
- **Vineet hard lock:** One serializer class + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - GET/create return item unit parity
  - Empty passthrough
  - Existing purchase-return ledger tests pass
  - **Unit gate:** `pytest products/tests/test_purchase_returns.py returns/tests/test_purchase_return_item_unit_oe339.py -q --no-cov` then `pytest --no-cov`

---

## OE-345 — F follow-on — `unit` on purchase-return `get_invoice_items`

- **Lane:** BE
- **Isolated file slice:** `returns/views.py` (`PurchaseReturnViewSet.get_invoice_items` dict only). Tests: `returns/tests/test_get_invoice_items_unit_oe340.py`.
- **Suggested base tip:** **After OE-320 SHIP** (same views file — do not parallel).
- **Done-when / AC:**
  1. Picker rows include `unit` from `item.product.unit` (null/empty passthrough).
  2. Existing qty / already_returned / purchase_price keys unchanged.
  3. Cross-tenant invoice still 404.
- **Out of scope:** OE-310 `PurchaseItemSerializer`; `search_order` (OE-320); FE modal (OE-339 can land first as optional).
- **Conflicts to avoid:** OE-320 in-flight on `returns/views.py`.
- **Vineet hard lock:** One action + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Invoice items include unit
  - Empty unit passthrough
  - Other-shop invoice 404
  - **Unit gate:** `pytest products/tests/test_purchase_returns.py returns/tests/test_get_invoice_items_unit_oe340.py -q --no-cov` then `pytest --no-cov`

---

## OE-346 — FE customer — optional featured / seasonal on ProductCard

- **Lane:** FE (customer_ordereasy_njs)
- **Isolated file slice:** `src/app/components/ProductCard.tsx` + `src/app/components/catalogBoolBadges.ts` + test.
- **Suggested base tip:** **After OE-316 SHIP** (same card — do not parallel).
- **Done-when / AC:**
  1. Types: `is_featured?: boolean | null`, `is_seasonal?: boolean | null`.
  2. `true` → compact muted Featured / Seasonal badge. `false` / null / absent → no badge.
  3. List/detail already expose both bools. No BE.
- **Out of scope:** Retailer OE-296/297/304; PDP (OE-347); write toggles.
- **Conflicts to avoid:** Parallel ProductCard with OE-316.
- **Vineet hard lock:** Display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - true/true both badges
  - false/absent none
  - brand line from OE-316 still works if stacked
  - **Unit gate:** customer helper tests

---

## OE-347 — FE customer — optional featured / seasonal on PDP

- **Lane:** FE (customer_ordereasy_njs)
- **Isolated file slice:** `src/app/retailer/product/page.tsx` + `src/app/retailer/product/pdpBoolBadges.ts` + test.
- **Suggested base tip:** **After OE-328 SHIP** (same PDP file).
- **Done-when / AC:**
  1. Same bool rules as OE-346, on the **detail** page title block.
  2. Missing/false → no badge. No BE.
- **Out of scope:** ProductCard (OE-346); shop header (OE-341); brand line (OE-328).
- **Conflicts to avoid:** Parallel PDP with OE-328.
- **Vineet hard lock:** Display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Featured/seasonal true/false
  - Brand line from OE-328 unchanged
  - **Unit gate:** customer `pdpBoolBadges` tests

---

## OE-348 — F follow-on — `barcode` on cart items

- **Lane:** BE
- **Isolated file slice:** `cart/serializers.py` (`CartItemSerializer`). Tests: `cart/tests/test_cart_item_barcode_oe343.py`.
- **Suggested base tip:** **After OE-314 SHIP** (same file).
- **Done-when / AC:**
  1. Cart item includes `barcode` matching product list/detail (null/empty passthrough).
  2. Do not change scan/add matching (OE-170 stays on lookup views).
  3. Auth/tenancy unchanged. OE-314 `brand_name` remains.
- **Out of scope:** Additional barcodes JSON; wishlist (OE-343); search Meta; FE cart brand (OE-329).
- **Conflicts to avoid:** Parallel OE-314 on `cart/serializers.py`.
- **Vineet hard lock:** One field + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Barcode echo / null passthrough
  - Auth denied
  - **Unit gate:** `pytest cart/tests/test_views.py cart/tests/test_cart_item_barcode_oe343.py -q --no-cov` then `pytest --no-cov`

---

## OE-349 — F follow-on — `barcode` on purchase invoice line items

- **Lane:** BE
- **Isolated file slice:** `products/serializers.py` (`PurchaseItemSerializer` only). Tests: `products/tests/test_purchase_item_barcode_oe344.py`.
- **Suggested base tip:** **After OE-310 SHIP.** Do **not** parallel OE-312 (same file, search Meta). Prefer #130 family after 310 is on the stack and 312 is not mid-edit.
- **Done-when / AC:**
  1. PI `items[]` includes `barcode` matching product list/detail (null/empty passthrough).
  2. OE-310 `unit` remains. No price math invent.
  3. Auth/tenancy unchanged. READ only.
- **Out of scope:** Search Meta (OE-312). POS no_page. FE purchase list (OE-309).
- **Conflicts to avoid:** Any in-flight `PurchaseItemSerializer` or `ProductSearchSerializer` Meta edit.
- **Vineet hard lock:** One serializer field + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - PI retrieve/create-read barcode parity
  - Null barcode passthrough
  - OE-310 unit non-regression
  - **Unit gate:** `pytest products/tests/test_purchase_invoice_item_unit_oe310.py products/tests/test_purchase_item_barcode_oe344.py -q --no-cov` then `pytest --no-cov`

---

## OE-350 — F follow-on — `unit` on inventory-ledger rows

- **Lane:** BE
- **Isolated file slice:** `products/api_erp_views.py` (`get_inventory_ledger` hand-built dict only). Tests: `products/tests/test_inventory_ledger_unit_oe345.py`.
- **Suggested base tip:** **After OE-315 SHIP** (same function). OE-315 already adds `product_id` / `product_name` / `barcode` — this ticket adds `unit` only.
- **Done-when / AC:**
  1. Each ledger row includes `unit` from `log.product.unit` (null/empty passthrough).
  2. Existing OE-315 identity keys unchanged. `select_related('product')` already present.
  3. Shop-wide `?reason=` filter still tenant-safe.
- **Out of scope:** Write-off POST; FE ledger (OE-318 / OE-351); POS views.
- **Conflicts to avoid:** Parallel OE-315 on `api_erp_views.py`.
- **Vineet hard lock:** One dict key + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Row `unit` matches product
  - Empty passthrough
  - Unauthenticated 401; customer 403
  - **Unit gate:** `pytest products/tests/test_inventory_ledger_identity_oe315.py products/tests/test_inventory_ledger_unit_oe345.py -q --no-cov` then `pytest --no-cov`

---

## OE-351 — FE — optional product identity on inventory ledger

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/app/dashboard/products/ledger/page.tsx` plus `src/utils/ledgerProductIdentity.ts` + test.
- **Suggested base tip:** **After OE-318 SHIP** (same page — batch_id) **and** after **OE-315 SHIP** (BE `product_name` / `barcode`).
- **Done-when / AC:**
  1. Types: `product_name?: string | null`, `barcode?: string | null` (unit optional if OE-350 landed).
  2. Trimmed non-empty name/barcode → muted identity line. Blank → hide. Do not invent.
  3. Do not regress OE-318 `batch_id` label.
- **Out of scope:** Write-off list (OE-326); reports (OE-319); POS.
- **Conflicts to avoid:** Parallel OE-318 on the ledger page.
- **Vineet hard lock:** Ledger display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Name/barcode present vs hidden
  - Batch # from OE-318 still renders
  - **Unit gate:** `npm test -- ledgerProductIdentity`

---

## OE-352 — F follow-on — `brand_name` on order line items

- **Lane:** BE
- **Isolated file slice:** `orders/serializers.py` (`OrderItemSerializer` only). Tests: `orders/tests/test_order_item_brand_oe347.py`.
- **Suggested base tip:** **After OE-301 SHIP** (same file — list fees).
- **Done-when / AC:**
  1. Order item JSON includes `brand_name` matching product list/detail (null stays null).
  2. List and detail both nest `OrderItemSerializer` — one field covers both.
  3. No N+1: `source='product.brand.name'` + existing item/product prefetch; add `product__brand` if missing.
  4. Auth/tenancy unchanged. READ only.
- **Out of scope:** Order list fees (OE-301); FE order detail (OE-325/330); cart (OE-314); search Meta.
- **Conflicts to avoid:** Parallel OE-301 on `orders/serializers.py`.
- **Vineet hard lock:** One item field + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Detail/list item `brand_name` parity with product
  - Null brand → null
  - Existing order list fee tests still pass after 301
  - **Unit gate:** `pytest orders/tests/test_serializers.py orders/tests/test_order_item_brand_oe347.py -q --no-cov` then `pytest --no-cov`

---

## OE-353 — FE — optional `unit` on purchase return-detail lines

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/app/dashboard/purchases/return-detail/page.tsx` plus `src/utils/purchaseReturnDetailUnit.ts` + test.
- **Suggested base tip:** **After OE-331 SHIP** (same page owns notes). Pair with OE-344 BE `unit` when present.
- **Done-when / AC:**
  1. Line type: `unit?: string | null`.
  2. Trimmed non-empty → muted unit beside qty. Blank → hide.
  3. Do not regress OE-331 notes block (already on the page today; 331 is the lock).
- **Out of scope:** PurchaseReturnModal (OE-339); purchase list (OE-309); sales-return detail (OE-327).
- **Conflicts to avoid:** Parallel OE-331 on return-detail.
- **Vineet hard lock:** Line display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Unit present / hidden
  - Notes block unchanged
  - **Unit gate:** `npm test -- purchaseReturnDetailUnit`

---

## Parallel CA slots (safe combos)

Run **at most one** editor per hot file.

| Slot | Ticket | File | Gate |
|------|--------|------|------|
| A | OE-339 | `PurchaseReturnModal.tsx` | Start now |
| B | OE-340 | `ProductForm.tsx` | Start now |
| C | OE-341 | customer `retailer/page.tsx` header | Start now |
| D | OE-342 | `POSReturnModal.tsx` | After OE-327 if same file |
| E | OE-343 | `customers/serializers.py` | After OE-305 |
| F | OE-344 | `returns/serializers.py` | After OE-313 |
| G | OE-345 | `returns/views.py` | After OE-320 |
| H | OE-346 | `ProductCard.tsx` | After OE-316 |
| I | OE-347 | customer PDP | After OE-328 |
| J | OE-348 | `cart/serializers.py` | After OE-314 |
| K | OE-349 | `PurchaseItemSerializer` | After OE-310; not parallel OE-312 |
| L | OE-350 | `api_erp_views.py` ledger | After OE-315 |
| M | OE-351 | retailer ledger page | After OE-318 |
| N | OE-352 | `OrderItemSerializer` | After OE-301 |
| O | OE-353 | purchase return-detail | After OE-331 |

Do **not** parallel: 313+344, 314+348, 315+350, 316+346, 320+345, 328+347, 331+353, 310+349+312, 301+352, 305+343, 318+351, 327+342 (if same file).

## Explicitly skipped

Epics; offline; notify; exchange; PIN/till; OE-102 / #103 rebuild; parallel offer/inventory engines; invented `StockMovement` SoT; further `ProductSearchSerializer` Meta until OE-312 SHIP; POS `products/views.py` row keys; cart serializers until OE-314 SHIP; returns serializers until OE-313 SHIP; returns views until OE-320 SHIP; any re-mint of OE-301–338; shop/supplier/order/customer **detail** pages already owned above.

If Jira’s next key is past OE-338 when minting, assign the next free keys and keep these file slices — do not force 339–353.
