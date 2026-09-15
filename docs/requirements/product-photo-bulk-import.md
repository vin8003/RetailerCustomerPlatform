# Product photo bulk import

- **Ticket:** [OE-124](https://vin8003.atlassian.net/browse/OE-124) · backlog `F-0027` · [snapshot](../tickets/OE-124.md)
- **Implementation:** EXTEND (`Product.image` + existing `ProductImage` / storage)
- **Depends on:** [pos-saleable-products.md](pos-saleable-products.md) (F-0017 catalog identity), [shop-staff-roles.md](shop-staff-roles.md) (`catalog.image`)

Import product photos in bulk and attach them to matching shop SKUs for POS and owned apps. This is **not** a second media library, DAM, or CDN product.

Identity stays the catalog fields already used on F-0017: `Product.id`, `Product.barcode`, `additional_barcodes`, and `ProductBatch.barcode`. There is no separate SKU column.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.image` as default for `image_display_url` / POS / owned apps | EXISTING |
| `Product.image_url` fallback | EXISTING |
| `ProductImage.is_primary` on additional images | EXISTING |
| `generate_upload_path` + default storage (local / S3 `product_images`) | EXISTING |
| Excel / scanner bulk product create | EXISTING — creates products; does not attach a zip of photos to existing SKUs |
| `POST /api/products/upload/images/` zip or csv+files | EXTEND |
| `catalog.image` permission | EXTEND (catalog v9) |
| `OrgAuditLog` `product_image` on successful attach | EXTEND |
| Parallel media library / marketplace DAM / FE gallery redesign | Out of scope |

## Matching

| Input | How it matches |
|-------|----------------|
| Zip of images named `{barcode}.jpg` / `{product_id}.png` | Filename stem |
| Zip + `manifest.csv` / `images.csv` / `mapping.csv` | CSV identity → filename in the zip |
| Multipart `csv` + `images` | CSV identity → uploaded filename |

CSV identity columns: `product_id`, `id`, `sku`, `barcode`. Filename columns: `filename`, `file`, `image`, `path`. Match is shop-scoped (`Product.retailer`). Ambiguous barcodes fail that row (`ambiguous SKU`).

Catalog match loads **only products that can match the import keys**, not the whole shop. Import rows and match keys are capped at **200** (`MAX_ROWS` / `MAX_MATCH_PRODUCTS`). The match queryset is not sliced, so a shared barcode still loads every partner and the row fails `ambiguous SKU`. The match path prefetches `batches` (needed for batch barcodes) and does **not** prefetch `additional_images` (`is_primary` is cleared with an UPDATE on attach).

Zip without a CSV: only `jpg` / `jpeg` / `png` / `gif` / `webp` become rows. Dotted junk (`readme.txt`, `Thumbs.db`, `__MACOSX`, `.*`) is ignored, not a failed row. Same basename (CSV lookup) or same stem (zip-only) **last-wins** — later zip member / later upload replaces the earlier file.

## Row policy

Failed rows (missing SKU, bad file, wrong type, missing file) are reported and **do not** abort the rest of the file. A broken zip/csv itself is **400** (nothing applied).

## Replace default

A successful attach writes the new file to `Product.image` (the object `image_display_url` already prefers). The previous `Product.image` file is deleted, `Product.image_url` is cleared, and additional `ProductImage.is_primary` flags are set false so the old object is not left as default.

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| POST | `/api/products/upload/images/` | Retailer JWT + `catalog.image` | Multipart `archive` (zip) and/or `csv` + `images`. **200** with per-row results. **403** without the perm (resource unchanged). Anonymous cannot upload. |

Cross-tenant ids/barcodes are **missing SKU** rows; tenant B cannot attach to tenant A.

## Audit

Successful attach appends `OrgAuditLog` (`object_type=product_image`) with before/after `image` name and `image_url`.

## Not in this change

Second media engine, marketplace DAM, FE matrix/gallery redesign, Jira Done, live `*.ordereasy.win`.
