# Optional HSN on purchase-return line items

- **Ticket:** [OE-339](https://vin8003.atlassian.net/browse/OE-339) · [snapshot](../tickets/OE-339.md)
- **Implementation:** EXTEND (optional echo of `Product.hsn_code` when the attribute exists)

Retailer purchase-return **line items** include top-level `hsn_code`. If the related product has an `hsn_code` attribute, the stored value is echoed. If the attribute is missing (this stack: Product has no HSN column), or the value is null, the payload is `null`. Empty string stays empty. This is a field echo, not a GST/HSN rebuild (KAN-57 / OE-57 / OE-102).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `PurchaseReturnItemSerializer` identity (`product`, `product_name`) | EXISTING |
| Optional `hsn_code` on purchase-return line items | EXTEND (OE-339) |
| `SalesReturnItemSerializer` | EXISTING (OE-313 owns that class — do not add HSN here) |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `products/views.py` | EXISTING — do not change |
| Product `hsn_code` column / GST slabs | Out of scope |

## API

| Method | Path | Who | `hsn_code` |
|--------|------|-----|------------|
| GET | `/api/returns/purchase/` | Authenticated retailer | Nested `items[].hsn_code` = `getattr(product, 'hsn_code', None)` |
| GET | `/api/returns/purchase/<id>/` | Authenticated retailer | Nested `items[].hsn_code` = `getattr(product, 'hsn_code', None)` |

Missing attribute → `null`. Null stays null. Empty stays empty. Do not invent an HSN.

Write payloads may include `hsn_code`; it is ignored. The SKU is not changed. Return write policy is unchanged.

Unauthenticated → **401**. Tenant B cannot read tenant A's return (absent / **404**).

`get_hsn_code` reads the product row already loaded for `product_name`. List/detail querysets prefetch items with `select_related('product', 'batch')` so the echo adds no extra product query.

## Not in this change

GST/HSN model rebuild, sales-return serializer (OE-313), search Meta, POS views, purchase invoice serializers, cart, ledger, unit conversion, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, FE, Jira Done, live `*.ordereasy.win`.
