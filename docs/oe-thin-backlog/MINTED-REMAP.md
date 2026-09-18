# Round-1 draft labels → minted Jira keys

PR **#143** drafted labels `OE-313`–`OE-327` **before** those keys existed. A later mint wave reused the numbers with **different titles**. Do **not** implement a round-1 draft against the minted key of the same number without checking this table.

| Round-1 draft label | Draft title (PR #143) | Minted key / actual title |
|---------------------|-----------------------|---------------------------|
| OE-313 | `unit` on sales-return items | **OE-313** — same (BE, flying #145) |
| OE-314 | product identity on inventory-ledger | **OE-315** — ledger identity (BE #147). Minted **OE-314** is cart `brand_name` |
| OE-315 | `brand_name` on cart items | **OE-314** — cart `brand_name` (BE #146) |
| OE-316 | ProductCard `brand_name` | **OE-316** — same (FE customer, flying) |
| OE-317 | reports expiring-batches | **OE-319** — reports expiring. Minted **OE-317** is purchase NEW costs |
| OE-318 | last-supplier-costs on purchase NEW | **OE-317** — purchase NEW costs. Minted **OE-318** is ledger `batch_id` |
| OE-319 | ProductCard featured/seasonal | **Not minted** — still draftable as OE-346 (after OE-316 SHIP) |
| OE-320 | customer order **list** fees | **OE-322** — customer order list fees. Minted **OE-320** is sales-return `search_order` `unit` |
| OE-321 | ledger `batch_id` | **OE-318** — ledger `batch_id`. Minted **OE-321** is customer **details** notes |
| OE-322 | customer **details** notes | **OE-321** — customer details notes. Minted **OE-322** is customer order list fees |
| OE-323 | `search_order` `unit` | **OE-320** — `search_order` `unit`. Minted **OE-323** is purchase **detail** notes |
| OE-324 | purchase-return `get_invoice_items` `unit` | **Not minted** — still draftable as OE-345 (after OE-320 SHIP) |
| OE-325 | `unit` on purchase-return items | **Not minted** — still draftable as OE-344 (after OE-313 SHIP) |
| OE-326 | `barcode` on cart items | **Not minted** — still draftable as OE-348 (after OE-314 SHIP). Minted **OE-326** is write-off **list** reason |
| OE-327 | `barcode` on PI line items | **Not minted** — still draftable as OE-349 (after OE-310 SHIP). Minted **OE-327** is sales-return **detail** notes |

Highest minted at round-2 scout: **OE-338**. New drafts start at **OE-339**.

### Also minted in the same wave (not from PR #143 drafts)

| Minted key | Actual title | Do not collide |
|------------|--------------|----------------|
| OE-323 | purchase **detail** notes | purchase detail / edit |
| OE-324 | supplier **detail** GST / terms | supplier detail |
| OE-325 | retailer order **detail** notes | `orders/details` |
| OE-326 | write-off **list** reason | write-off list |
| OE-327 | sales-return **detail** notes | sales-return detail / maybe POSReturnModal |
| OE-328 | customer PDP `brand_name` | `retailer/product/page.tsx` |
| OE-329 | customer cart `brand_name` | `cart/page.tsx` |
| OE-330 | retailer order detail **phone** | `orders/details` |
| OE-331 | purchase-return **detail** notes | `purchases/return-detail` |
| OE-332 | customer wishlist `brand_name` | `wishlist/page.tsx` |
| OE-333 | khata ledger **list** notes | khata list |
| OE-334 | POS cart line `brand_name` | `pos/page.tsx` |
| OE-335 | customer order **detail** notes | `orders/detail` |
| OE-336 | sales-return **list** notes | sales-return list |
| OE-337 | supplier **list** email | `suppliers/page.tsx` |
| OE-338 | customer product **list** `unit` | shop list helpers, not ProductCard |
