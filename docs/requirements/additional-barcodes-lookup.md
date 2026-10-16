# Additional barcodes in POS / catalog lookup

- **Ticket:** [OE-170](https://vin8003.atlassian.net/browse/OE-170) · backlog `F-0072` (thin slice) · [snapshot](../tickets/OE-170.md)
- **Implementation:** EXTEND (`smart_product_search` already used by POS and catalog)
- **Depends on:** [pos-saleable-products.md](pos-saleable-products.md) (F-0017 catalog identity)
- **Related:** [search-barcode.md](search-barcode.md) (OE-290 primary `barcode` echo on search rows)

POS and catalog product search resolve `Product.additional_barcodes` the same way they already resolve primary `Product.barcode`. The field name stays `additional_barcodes`. Match is the existing `icontains` path (query is space-normalized and lowercased first). Lookups stay retailer-scoped.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.additional_barcodes` JSONField | EXISTING |
| `GET /api/products/?search=` (POS `no_page`) | EXTEND — additional barcodes |
| `GET /api/products/search/?search=` | EXTEND — additional barcodes |
| Public `…/retailer/<id>/search/` | EXTEND — same helper, still shop-scoped |
| Printer HAL, price-encoded labels, FE label designer | Out of scope |

Tenancy is unchanged: retailer A cannot see retailer B's SKU by sharing an additional barcode.

Photo import already matched additional barcodes for attach (OE-124). This slice is search/lookup only.
