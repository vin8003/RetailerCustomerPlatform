# Product unit on purchase invoice line items

- **Ticket:** [OE-310](https://vin8003.atlassian.net/browse/OE-310) · [snapshot](../tickets/OE-310.md)
- **Implementation:** EXTEND (echo existing `Product.unit` on purchase items)

Retailer purchase invoice **line items** include top-level `unit` with the same value already returned by product list/detail (`Product.unit`). This is a field echo, not a conversion engine.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.unit` on list / detail serializers | EXISTING |
| `unit` on purchase invoice line items | EXTEND (OE-310) |
| `ProductSearchSerializer` Meta `unit` | EXISTING — do not change (OE-312 owns search Meta) |
| POS `no_page` `unit` | EXISTING (OE-286) — do not change |
| Unit conversion, write APIs, default invent on read | Out of scope |

## API

| Method | Path | Who | `unit` |
|--------|------|-----|--------|
| GET | `/api/products/erp/purchase-invoices/` | Authenticated retailer | Nested `items[].unit` = `Product.unit` |
| GET | `/api/products/erp/purchase-invoices/<id>/` | Authenticated retailer | Nested `items[].unit` = `Product.unit` |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |

Empty or null `unit` stays empty/null. Reads do not invent `piece` unless that is the stored model value (the field default is still `piece` on create). Missing product on a line (`SET_NULL`) → `unit` is `null`.

Write payloads may include `unit`; it is ignored. The stored SKU unit is not changed.

Unauthenticated → **401**. Tenant B cannot read tenant A's invoice (absent / **404**).

`source='product.unit'` reuses the product row already loaded for `product_name`. No extra product query when `select_related('product')` is present.

## Not in this change

Unit conversion, pack write, inventory.adjust, search Meta, POS views, timeline/OFD/khata/UPI/slots, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
