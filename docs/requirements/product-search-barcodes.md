# Product search barcodes

- **Ticket:** [KAN-72](https://vin8003.atlassian.net/browse/KAN-72) · [snapshot](../tickets/KAN-72.md)

Retailer product search (`GET /api/products/?search=` and `GET /api/products/search/`) matches:

- `Product.barcode`
- `Product.additional_barcodes`
- `ProductBatch.barcode`
- `ProductBatch.additional_barcodes`

POS and purchase entry already match those codes in the retailer app. Products search uses this API.
