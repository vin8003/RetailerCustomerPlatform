# OrderEasy thin backlog (scout, 2026-09-18)

Prioritized mint-ready thins so the ticket pipeline does not bottleneck CA slots. **Docs only.** Keys `OE-313`–`OE-327` are **draft labels** for minting — they are not Jira issues yet (highest minted at scout: **OE-312**).

Scout base: BE PR **#130** tip `d022f37` (OE-300 PASS). Do not invent layers, epics, offline, notify, exchange, PIN, OE-102 / #103 rebuild, or parallel engines.

## Vineet hard lock (every ticket)

Copy this block into each minted Jira card:

- Surgical slice only. Keep timeline / OFD / khata / UPI / slots / `inventory.adjust` / pack **write** intact.
- **Dummy / local only.** Never hit `*.ordereasy.win`.
- **No merge.** **Do not mark Done.** Leave status Dev Ready / In Review.
- No new services, no N+1, no write-path invent, no GST / HSN rebuild (KAN-57 / OE-102).

## Isolation — do not collide

| Hot surface | Owner now | Rule |
|-------------|-----------|------|
| `products/serializers.py` `ProductSearchSerializer` Meta | **OE-303** (#140) then **OE-312** | Do **not** propose another search Meta field until OE-303 **SHIP**. OE-312 already queues `is_in_stock`. |
| `customers/serializers.py` | **OE-305** (#141) | Do not add list/detail customer scalars or wishlist fields until OE-305 SHIP. |
| `products/views.py` POS `?no_page=true` | **OE-286** + **OE-302** (#139) | Do not add POS row keys. |
| `products/serializers.py` `PurchaseItemSerializer` | **OE-310** | No PI line fields until OE-310 SHIP. Then OE-327 (`barcode`) only. |
| `orders/serializers.py` | **OE-301** (#138) | No order list/detail Meta until OE-301 SHIP. |
| Retailer FE catalog + POS tiles | **OE-304** (#55) also OE-288/289/292/296/297 | Do not touch `ProductTable.tsx`, `VirtualProductList.tsx`, `pos/page.tsx`, availability badge files. |
| Retailer FE customers **list** | **OE-306** (#56) | `customers/page.tsx` + `CustomerListScalars*` locked. **Details** page is free. |
| Retailer FE orders **list** | **OE-307** (#57) | `OrderTable.tsx` + `orderFeeDiscount*` locked. **Details** page already shows fees. |
| Retailer FE suppliers **list** | **OE-308** (#58) | `suppliers/page.tsx` + `SupplierListScalars*` locked. Ledger page is free (already shows invoice #). |
| Retailer FE purchases **list** | **OE-309** (in progress) | `purchases/page.tsx` locked. **new** / **edit** / **return-detail** are free. |

## Already minted (do not re-mint)

| Key | Lane | Status (scout) | Why skip |
|-----|------|----------------|----------|
| OE-301 | BE | In Review #138 | `delivery_fee` / `discount_amount` on order list |
| OE-302 | BE | In Review #139 | POS no_page availability bools |
| OE-303 | BE | In Review #140 | search `is_available` (HOT Meta) |
| OE-304 | FE retailer | In Review #55 | catalog/POS unavailable / OOS badges |
| OE-305 | BE | In Progress #141 | customer list scalars |
| OE-306 | FE retailer | In Review #56 | customer list display |
| OE-307 | FE retailer | In Review #57 | order list fee lines |
| OE-308 | FE retailer | In Review #58 | supplier list GST / terms |
| OE-309 | FE retailer | In Progress | purchase **list** notes |
| OE-310 | BE | In Progress | PI line `unit` |
| OE-311 | FE customer | Dev Ready | order **detail** fees |
| OE-312 | BE | Dev Ready | search `is_in_stock` — **after OE-303 SHIP only** |

## Priority index

| P | Draft key | Title | Lane | Start now? |
|---|-----------|-------|------|------------|
| 1 | OE-313 | F follow-on — `unit` on sales-return items | BE | Yes — #130 sibling |
| 2 | OE-314 | F follow-on — product identity on inventory-ledger rows | BE | Yes — #130 sibling |
| 3 | OE-315 | F follow-on — `brand_name` on cart items | BE | Yes — #130 sibling |
| 4 | OE-316 | FE customer — optional `brand_name` on ProductCard | FE (customer_ordereasy_njs) | Yes — customer tip sibling |
| 5 | OE-317 | FE — expiring-batches panel on reports | FE (retailer_ordereasy_njs) | Yes — #54 sibling |
| 6 | OE-318 | FE — last-supplier-costs on purchase NEW | FE (retailer_ordereasy_njs) | Yes — #54 sibling |
| 7 | OE-319 | FE customer — optional featured / seasonal badges on ProductCard | FE (customer_ordereasy_njs) | After or sibling of OE-316 (same card) |
| 8 | OE-320 | FE customer — optional fee / discount on order **list** | FE (customer_ordereasy_njs) | Yes (optional keys; BE via OE-301) |
| 9 | OE-321 | FE — `batch_id` on inventory ledger | FE (retailer_ordereasy_njs) | Yes — #54 sibling |
| 10 | OE-322 | FE — mapping `notes` on customer **details** | FE (retailer_ordereasy_njs) | Yes — not OE-306 list |
| 11 | OE-323 | F follow-on — `unit` on sales-return `search_order` picker | BE | Yes — `returns/views.py` |
| 12 | OE-324 | F follow-on — `unit` on purchase-return `get_invoice_items` | BE | After OE-323 (same file) |
| 13 | OE-325 | F follow-on — `unit` on purchase-return items | BE | After OE-313 (same serializers file) |
| 14 | OE-326 | F follow-on — `barcode` on cart items | BE | After OE-315 (same cart serializers file) |
| 15 | OE-327 | F follow-on — `barcode` on purchase invoice line items | BE | **After OE-310 SHIP** only |

---

## OE-313 — F follow-on — `unit` on sales-return items

- **Lane:** BE
- **Isolated file slice:** `returns/serializers.py` (`SalesReturnItemSerializer` only). Tests: `returns/tests/test_sales_returns.py` (add focused file `returns/tests/test_sales_return_item_unit_oe313.py` if cleaner).
- **Suggested base tip:** BE **#130** sibling (`d022f37`). Do not stack on #139/#140/#141.
- **Done-when / AC:**
  1. GET/create sales-return payload `items[]` includes `unit` matching `product.unit` for the same SKU (null/empty stays null/empty — no invented `piece`).
  2. Auth / shop tenancy unchanged (401 / other-shop 404 or empty).
  3. Plain `CharField(source='product.unit')` or equivalent — no MethodField math, no N+1 (`select_related('product')` if the view queryset does not already).
  4. READ echo only — no return write-policy change.
- **Out of scope:** Purchase-return serializer (OE-325); `search_order` picker dict (OE-323); POS no_page; search Meta; FE.
- **Conflicts to avoid:** Not `ProductSearchSerializer` Meta (OE-303). Not `customers/serializers.py` (OE-305). Not `products/views.py` (OE-286/302). Not OE-304/306/307/308/309 FE sets.
- **Vineet hard lock:** Returns serializer + tests only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Happy: return item `unit` equals product list/detail `unit`
  - Empty/null unit passthrough
  - Auth denied
  - Other-shop product not leaked
  - Existing sales-return stock / points tests still pass
  - **Unit gate:** `pytest returns/tests/test_sales_returns.py returns/tests/test_sales_return_item_unit_oe313.py -q --no-cov` then `pytest --no-cov`

---

## OE-314 — F follow-on — product identity on inventory-ledger rows

- **Lane:** BE
- **Isolated file slice:** `products/api_erp_views.py` (`get_inventory_ledger` hand-built dict only). Tests: extend `products/tests/test_write_off_oe141.py` (`TestWriteOffLedgerFilter`) or add `products/tests/test_inventory_ledger_product_identity_oe314.py`.
- **Suggested base tip:** BE **#130** sibling. Do **not** edit `products/views.py`.
- **Done-when / AC:**
  1. Each ledger row includes `product_id`, `product_name`, and `unit` from `log.product` (unit null/empty stays null/empty).
  2. Shop-wide `?reason=` filter (already supported) still hides other-tenant rows; identity fields match the log’s product.
  3. Existing keys (`id`, `log_type`, `batch_id`, qty fields, `reason`, `created_at`, `created_by`) unchanged.
  4. `select_related('product')` already-or-added so no per-row product query.
- **Out of scope:** Write-off POST; POS catalog; search Meta; FE (OE-321 displays `batch_id` that already exists).
- **Conflicts to avoid:** Not POS views (OE-286/302). Not `PurchaseItemSerializer` (OE-310). Not search Meta (OE-303).
- **Vineet hard lock:** One ERP view function + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Happy: `?product_id=` row has matching `product_id` / `product_name` / `unit`
  - Shop-wide `?reason=damage` includes identity; tenant B omitted
  - Missing `product_id` and `reason` still 400
  - Unauthenticated 401; customer 403
  - **Unit gate:** `pytest products/tests/test_write_off_oe141.py products/tests/test_inventory_ledger_product_identity_oe314.py -q --no-cov` then `pytest --no-cov`

---

## OE-315 — F follow-on — `brand_name` on cart items

- **Lane:** BE
- **Isolated file slice:** `cart/serializers.py` (`CartItemSerializer` only). Tests: `cart/tests/test_views.py` and/or `cart/tests/test_cart_item_brand_oe315.py`.
- **Suggested base tip:** BE **#130** sibling.
- **Done-when / AC:**
  1. Cart item JSON includes `brand_name` matching product list/detail (`product.brand.name` or null).
  2. Null brand → `null` (do not invent from product name).
  3. Auth: customer only; retailer 403; anonymous 401. Tenancy: cart still shop-scoped.
  4. No extra query per line if `product__brand` can be selected on the existing cart queryset (add `select_related` on the cart view **only if** required — prefer serializer source + one join).
- **Out of scope:** Cart write/qty rules; barcode (OE-326); wishlist (OE-305 file lock); search Meta.
- **Conflicts to avoid:** Not customers/serializers (OE-305). Not POS views. Not FE OE-304 catalog files.
- **Vineet hard lock:** Cart serializer (+ view select_related if needed) + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Happy: branded SKU echoes list `brand_name`
  - Null brand → null
  - Auth denied / retailer forbidden
  - Existing add-to-cart tests pass
  - **Unit gate:** `pytest cart/tests/test_views.py cart/tests/test_cart_item_brand_oe315.py -q --no-cov` then `pytest --no-cov`

---

## OE-316 — FE customer — optional `brand_name` on ProductCard

- **Lane:** FE (customer_ordereasy_njs)
- **Isolated file slice:** `src/app/components/ProductCard.tsx` (+ `ProductCard.module.css` if needed), tiny helper `src/app/components/productBrandLabel.ts` + `productBrandLabel.test.ts`. Do **not** restyle InfiniteProductGrid layout beyond passing the field.
- **Suggested base tip:** Latest customer app main / stacked customer tip (sibling of customer #22/#23). Not retailer #54 files.
- **Done-when / AC:**
  1. Types: `brand_name?: string | null`.
  2. When non-empty trimmed string, show muted line under the title. Missing/null/blank → no invent / no placeholder.
  3. Public catalog already sends `brand_name` on list (ProductListSerializer). No new API.
  4. Unit tests for helper (present → text; blank → null).
- **Out of scope:** Featured/seasonal (OE-319); retailer catalog (OE-304); BE; PDP rewrite.
- **Conflicts to avoid:** Not retailer OE-304/306/307/308/309. Not customer order **detail** (OE-311).
- **Vineet hard lock:** ProductCard display only. Do not break add-to-cart / wishlist / UPI / slots. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Present brand renders
  - Absent/blank renders nothing
  - Offer badge + discount badge still render
  - **Unit gate:** repo’s existing `npm test` / `npx vitest` / `npx jest` for the new helper (match customer repo script)

---

## OE-317 — FE — expiring-batches panel on reports

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/app/dashboard/reports/page.tsx` plus `src/components/reports/ExpiringBatchesPanel.tsx` + `ExpiringBatchesPanel.test.tsx` + `src/utils/expiringBatchRow.ts` + test. **Do not** touch `pos/page.tsx`, `ProductTable.tsx`, `purchases/page.tsx`.
- **Suggested base tip:** Retailer FE **#54** sibling (`4389e38` / current #54 tip).
- **Done-when / AC:**
  1. Reports page fetches `GET /api/products/erp/expiring-batches/` (OE-210 already on BE tip).
  2. Show compact table/cards: `product_name`, `batch_number`, `expiry_date`, `quantity`, optional `is_expired` badge when `true`.
  3. Empty list → muted empty state, not invented rows. 403/401 → existing toast pattern.
  4. No notify, no MIS engine, no write-off from this panel.
- **Out of scope:** Full F-0125 MIS; write-off UI (#42); catalog/POS (OE-304); purchase list (OE-309).
- **Conflicts to avoid:** OE-304/306/307/308/309 file sets. Not `products/views.py`.
- **Vineet hard lock:** Reports panel only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Rows when API returns batches
  - Empty array → empty state
  - `is_expired === true` badge; false/absent → no badge
  - **Unit gate:** retailer FE unit test command for the new helper/panel (match repo script, typically `npm test -- ExpiringBatches`)

---

## OE-318 — FE — last-supplier-costs on purchase NEW

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/app/dashboard/purchases/new/page.tsx` plus `src/utils/lastSupplierCosts.ts` + test + optional `src/components/purchases/LastSupplierCosts.tsx`. **Not** `purchases/page.tsx` (OE-309).
- **Suggested base tip:** Retailer FE **#54** sibling.
- **Done-when / AC:**
  1. When a line’s product is chosen, purchase-role GET `/api/products/erp/products/<id>/last-supplier-costs/` (OE-112).
  2. If `suppliers.length > 0`, show compact muted list: supplier name + `last_cost` + invoice date. Empty `[]` → hide (no `₹0` invent).
  3. 403 (cashier) → hide quietly (same as margin badge). 404 → hide.
  4. Display only — do not auto-fill purchase_price unless already how the page works (do **not** start auto-fill in this ticket).
- **Out of scope:** OE-102 PO; compare matrix; PI list notes (OE-309); PI line `unit` write (OE-310).
- **Conflicts to avoid:** OE-309 list page; OE-304 catalog; OE-308 supplier list.
- **Vineet hard lock:** Purchase NEW only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Non-empty suppliers render
  - Empty array hidden
  - Stored `0.00` cost still shown (real history)
  - **Unit gate:** `npm test -- lastSupplierCosts` (or repo equivalent)

---

## OE-319 — FE customer — optional featured / seasonal badges on ProductCard

- **Lane:** FE (customer_ordereasy_njs)
- **Isolated file slice:** `ProductCard.tsx` + `src/app/components/catalogBoolBadges.ts` + test. Prefer **after OE-316** if both edit ProductCard (do not parallel the same file).
- **Suggested base tip:** Customer tip; stack on OE-316 branch if that PR is open.
- **Done-when / AC:**
  1. Types: `is_featured?: boolean | null`, `is_seasonal?: boolean | null`.
  2. `true` → compact muted Featured / Seasonal badge. `false` / null / absent → no badge.
  3. List/detail already expose both bools. No BE.
- **Out of scope:** Retailer OE-296/297/304; write toggles; search Meta.
- **Conflicts to avoid:** Parallel ProductCard with OE-316. Retailer OE-304 file set.
- **Vineet hard lock:** Display only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - true/true both badges
  - false/absent none
  - brand line from OE-316 still works if stacked
  - **Unit gate:** customer helper tests

---

## OE-320 — FE customer — optional fee / discount on order **list**

- **Lane:** FE (customer_ordereasy_njs)
- **Isolated file slice:** `src/app/orders/page.tsx` + `src/app/orders/orderListFeeLines.ts` + test. **Not** `src/app/orders/detail/page.tsx` (OE-311).
- **Suggested base tip:** Customer tip sibling of OE-311.
- **Done-when / AC:**
  1. Types: `delivery_fee?`, `discount_amount?`.
  2. When present and numeric ≠ 0, muted fee/discount near total. Missing/null/0 → no line.
  3. BE: OE-301 lands fields on `OrderListSerializer` (customer list uses the same list serializer). Until #138 merges, optional keys simply stay hidden.
- **Out of scope:** Retailer OrderTable (OE-307); payment invent; status machine.
- **Conflicts to avoid:** OE-311 detail files; retailer OE-307.
- **Vineet hard lock:** Customer order **list** only. Do not break timeline / UPI / slots. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Non-zero fee/discount lines
  - Zero/null hidden
  - **Unit gate:** customer helper tests

---

## OE-321 — FE — `batch_id` on inventory ledger

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/app/dashboard/products/ledger/page.tsx` + `src/utils/ledgerBatchLabel.ts` + test.
- **Suggested base tip:** Retailer FE **#54** sibling.
- **Done-when / AC:**
  1. Ledger type includes `batch_id?: number | null` (BE already returns it from OE-141).
  2. When `batch_id` is a positive number, show muted `Batch #N`. Null/absent → no invent.
  3. No new API. Do not wait for OE-314 (product identity) unless stacking later.
- **Out of scope:** Write-off POST UI; reports expiry (OE-317); POS.
- **Conflicts to avoid:** OE-304 catalog/POS; products list pages.
- **Vineet hard lock:** Ledger page only. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Present batch_id label
  - Null hidden
  - **Unit gate:** retailer helper tests

---

## OE-322 — FE — mapping `notes` on customer **details**

- **Lane:** FE (retailer_ordereasy_njs)
- **Isolated file slice:** `src/app/dashboard/customers/details/page.tsx` + `src/utils/customerDetailNotes.ts` + test. **Not** `customers/page.tsx` (OE-306).
- **Suggested base tip:** Retailer FE **#54** sibling.
- **Done-when / AC:**
  1. Detail already has BE `notes` (`RetailerCustomerDetailSerializer`). Show when trimmed non-empty.
  2. Missing/null/blank → no placeholder card.
  3. Do not add credit write or blacklist UI.
- **Out of scope:** Customer **list** (OE-306); BE OE-305; khata payment notes (already on the page).
- **Conflicts to avoid:** OE-306 list scalars files.
- **Vineet hard lock:** Details page display only. Do not break khata / UPI. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Non-empty notes render
  - Blank hidden
  - **Unit gate:** retailer helper tests

---

## OE-323 — F follow-on — `unit` on sales-return `search_order` picker

- **Lane:** BE
- **Isolated file slice:** `returns/views.py` (`SalesReturnViewSet.search_order` hand-built `items_data` dict only). Tests: `returns/tests/test_sales_returns.py` or `returns/tests/test_search_order_unit_oe323.py`.
- **Suggested base tip:** BE **#130** sibling (parallel with OE-313 — **different file**).
- **Done-when / AC:**
  1. Each picker item includes `unit` from `item.product.unit` (null/empty passthrough).
  2. Existing keys (`id`, `product_id`, `product_name`, qty, `unit_price`, `batch_id`) unchanged.
  3. Auth/tenancy unchanged; still delivered-only search.
- **Out of scope:** Serializer GET (OE-313); purchase `get_invoice_items` (OE-324); return write.
- **Conflicts to avoid:** Not POS views. Not search Meta. Sequential with OE-324 on this same views file.
- **Vineet hard lock:** One action + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Search hit includes unit parity with product
  - Empty unit passthrough
  - No match 404; unauthenticated 401
  - **Unit gate:** `pytest returns/tests/test_sales_returns.py returns/tests/test_search_order_unit_oe323.py -q --no-cov` then `pytest --no-cov`

---

## OE-324 — F follow-on — `unit` on purchase-return `get_invoice_items`

- **Lane:** BE
- **Isolated file slice:** `returns/views.py` (`PurchaseReturnViewSet.get_invoice_items` dict only).
- **Suggested base tip:** Stack on **OE-323** branch / #130 after OE-323 SHIP (same file — do not parallel).
- **Done-when / AC:**
  1. Picker rows include `unit` from `item.product.unit` (null/empty passthrough).
  2. Existing qty / already_returned / purchase_price keys unchanged.
  3. Cross-tenant invoice still 404.
- **Out of scope:** OE-310 `PurchaseItemSerializer`; PI write; FE purchase list (OE-309).
- **Conflicts to avoid:** OE-323 in-flight on `returns/views.py`. OE-310 on `products/serializers.py`.
- **Vineet hard lock:** One action + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Invoice items include unit
  - Empty unit passthrough
  - Other-shop invoice 404
  - **Unit gate:** `pytest products/tests/test_purchase_returns.py returns/tests/test_get_invoice_items_unit_oe324.py -q --no-cov` then `pytest --no-cov`

---

## OE-325 — F follow-on — `unit` on purchase-return items

- **Lane:** BE
- **Isolated file slice:** `returns/serializers.py` (`PurchaseReturnItemSerializer` only).
- **Suggested base tip:** Stack on **OE-313** (same file — do not parallel).
- **Done-when / AC:**
  1. Purchase-return `items[]` includes `unit` matching product (null/empty passthrough).
  2. Auth/tenancy unchanged.
  3. READ echo only.
- **Out of scope:** Sales-return serializer (OE-313); picker views (OE-323/324); OE-310.
- **Conflicts to avoid:** Parallel OE-313 on `returns/serializers.py`.
- **Vineet hard lock:** One serializer class + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - GET/create return item unit parity
  - Empty passthrough
  - Existing purchase-return ledger tests pass
  - **Unit gate:** `pytest products/tests/test_purchase_returns.py returns/tests/test_purchase_return_item_unit_oe325.py -q --no-cov` then `pytest --no-cov`

---

## OE-326 — F follow-on — `barcode` on cart items

- **Lane:** BE
- **Isolated file slice:** `cart/serializers.py` (`CartItemSerializer`).
- **Suggested base tip:** Stack on **OE-315** (same file).
- **Done-when / AC:**
  1. Cart item includes `barcode` matching product list/detail (null/empty passthrough).
  2. Do not change scan/add matching (OE-170 stays on lookup views).
  3. Auth/tenancy unchanged.
- **Out of scope:** Additional barcodes JSON blob; wishlist (OE-305 lock); search Meta.
- **Conflicts to avoid:** Parallel OE-315 on `cart/serializers.py`.
- **Vineet hard lock:** One field + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - Barcode echo / null passthrough
  - Auth denied
  - **Unit gate:** `pytest cart/tests/test_views.py cart/tests/test_cart_item_barcode_oe326.py -q --no-cov` then `pytest --no-cov`

---

## OE-327 — F follow-on — `barcode` on purchase invoice line items

- **Lane:** BE
- **Isolated file slice:** `products/serializers.py` (`PurchaseItemSerializer` only).
- **Suggested base tip:** **After OE-310 SHIP.** Then sibling or stack on the OE-310 tip (not #140 search Meta). Prefer BE **#130** family only after 310 is on the stack.
- **Done-when / AC:**
  1. PI `items[]` includes `barcode` matching product list/detail (null/empty passthrough).
  2. OE-310 `unit` remains. No price math invent.
  3. Auth/tenancy unchanged. READ only.
- **Out of scope:** Search Meta (OE-303/312). POS no_page (OE-286). Customer serializers (OE-305). FE purchase list (OE-309).
- **Conflicts to avoid:** Any in-flight `PurchaseItemSerializer` or `ProductSearchSerializer` Meta edit. Do not start until OE-310 SHIP.
- **Vineet hard lock:** One serializer field + tests. Dummy only. No merge. No Done. Never `*.ordereasy.win`.
- **QA pack:**
  - PI retrieve/create-read barcode parity
  - Null barcode passthrough
  - OE-310 unit non-regression
  - **Unit gate:** `pytest products/tests/test_purchase_returns.py products/tests/test_purchase_invoice_supplier_gate_oe100.py products/tests/test_purchase_item_barcode_oe327.py -q --no-cov` then `pytest --no-cov`

---

## Parallel CA slots (safe combos)

Run **at most one** editor per hot file.

| Slot | Ticket | File |
|------|--------|------|
| A | OE-313 | `returns/serializers.py` |
| B | OE-314 | `products/api_erp_views.py` |
| C | OE-315 | `cart/serializers.py` |
| D | OE-316 | customer `ProductCard.tsx` |
| E | OE-317 | retailer `reports/page.tsx` |
| F | OE-318 | retailer `purchases/new/page.tsx` |
| G | OE-320 | customer `orders/page.tsx` |
| H | OE-321 | retailer `products/ledger/page.tsx` |
| I | OE-322 | retailer `customers/details/page.tsx` |
| J | OE-323 | `returns/views.py` |

Do **not** parallel: 313+325, 315+326, 316+319, 323+324, 327+310, any search Meta + OE-303.

## Explicitly skipped

Epics; offline; notify; exchange; PIN/till; OE-102 / #103 rebuild; parallel offer/inventory engines; invented `StockMovement` SoT; further `ProductSearchSerializer` Meta (until OE-303 SHIP; OE-312 already queued); POS `products/views.py` row keys; `customers/serializers.py` until OE-305 SHIP; retailer catalog/POS badge files owned by OE-304 and siblings.
