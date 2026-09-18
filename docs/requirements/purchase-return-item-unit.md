# Product unit on purchase-return line items

- **Ticket:** [OE-355](https://vin8003.atlassian.net/browse/OE-355) · [snapshot](../tickets/OE-355.md)
- **Sibling:** [OE-313](https://vin8003.atlassian.net/browse/OE-313) sales-return items (different serializer)
- **Implementation:** EXTEND (echo existing `Product.unit` on purchase-return items)

Retailer purchase-return **line items** include top-level `unit` when `product.unit` exists, matching product list/detail (`Product.unit`) and the purchase-line OE-310 pattern. This is a field echo, not a conversion engine. Sales-return `unit` stays on `SalesReturnItemSerializer` (OE-313).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.unit` on list / detail serializers | EXISTING |
| `unit` on purchase invoice line items | OE-310 (sibling; do not change here) |
| `unit` on sales-return line items | EXISTING / flying (OE-313) — do not change |
| `unit` on purchase-return line items | EXTEND (this slice) |
| `get_invoice_items` picker `unit` | Out of scope (separate slice) |
| Unit conversion, write APIs, default invent on read | Out of scope |

## API

| Method | Path | Who | `unit` |
|--------|------|-----|--------|
| GET | `/api/returns/purchase/` | Authenticated retailer | Nested `items[].unit` = `Product.unit` when present |
| GET | `/api/returns/purchase/<id>/` | Authenticated retailer | Nested `items[].unit` = `Product.unit` when present |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |

Empty or null `unit` stays empty/null. Reads do not invent `piece` unless that is the stored model value (the field default is still `piece` on create). If `product` is missing or has no `unit` attribute, the echo is `null`.

Write payloads may include `unit`; it is ignored. The stored SKU unit is not changed. Return write policy is unchanged.

Unauthenticated → **401**. Tenant B cannot read tenant A's return (absent / **404**). Dummy / local only.

`source='product.unit'` reuses the product row already loaded for `product_name`. List/detail querysets prefetch items with `select_related('product')` so the echo adds no extra product query.

## Not in this change

`SalesReturnItemSerializer` (OE-313), `get_invoice_items`, unit conversion, pack write, inventory.adjust, search Meta, POS views, customers/*, orders serializers, purchase invoice serializers, timeline/OFD/khata/UPI/slots, notify, FE redesign, Jira Done, live `*.ordereasy.win`.
