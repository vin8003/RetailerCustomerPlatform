# Product unit on sales-return line items

- **Ticket:** [OE-313](https://vin8003.atlassian.net/browse/OE-313) · [snapshot](../tickets/OE-313.md)
- **Implementation:** EXTEND (echo existing `Product.unit` on sales-return items)

Retailer sales-return **line items** include top-level `unit` with the same value already returned by product list/detail (`Product.unit`), matching the purchase-line OE-310 pattern. This is a field echo, not a conversion engine.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.unit` on list / detail serializers | EXISTING |
| `unit` on purchase invoice line items | EXISTING (OE-310) — do not change |
| `unit` on sales-return line items | EXTEND (OE-313) |
| `ProductSearchSerializer` Meta `unit` | EXISTING — do not change |
| POS `no_page` `unit` | EXISTING (OE-286) — do not change |
| Unit conversion, write APIs, default invent on read | Out of scope |

## API

| Method | Path | Who | `unit` |
|--------|------|-----|--------|
| GET | `/api/returns/sales/` | Authenticated retailer | Nested `items[].unit` = `Product.unit` |
| GET | `/api/returns/sales/<id>/` | Authenticated retailer | Nested `items[].unit` = `Product.unit` |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |

Empty or null `unit` stays empty/null. Reads do not invent `piece` unless that is the stored model value (the field default is still `piece` on create). `SalesReturnItem.product` is required, so a missing product cannot occur on a persisted line.

Write payloads may include `unit`; it is ignored. The stored SKU unit is not changed. Return write policy is unchanged.

Unauthenticated → **401**. Tenant B cannot read tenant A's return (absent / **404**).

`source='product.unit'` reuses the product row already loaded for `product_name`. List/detail querysets prefetch items with `select_related('product')` so the echo adds no extra product query.

## Not in this change

Unit conversion, pack write, inventory.adjust, search Meta, POS views, customers/*, orders serializers, purchase invoice serializers, timeline/OFD/khata/UPI/slots, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
