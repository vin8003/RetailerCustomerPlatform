# POS only sells active, available products

- **Ticket:** [OE-190](https://vin8003.atlassian.net/browse/OE-190) · [snapshot](../tickets/OE-190.md)
- **API:** `POST /api/products/erp/pos-checkout/` (`create_pos_order`)

An **inactive** (`is_active=False`) or **unavailable** (`is_available=False`) product cannot be sold on a new POS order. The backend returns **400** with the product name and id. Retailer tenancy is unchanged: the product is still loaded as `id` + `retailer`.

This matches customer cart (`AddToCartSerializer` requires `is_active=True` and `is_available=True`). POS UI already filters `is_active=true`; this rule closes the checkout hole if the client sends a stale or crafted id.

Identity remains `Product.id` (and barcode on Product / ProductBatch, plus `Product.additional_barcodes` in POS/catalog search — [additional-barcodes-lookup.md](additional-barcodes-lookup.md)). There is no separate SKU column.
