# Optional is_serialized on product list/detail

- **Ticket:** [OE-366](https://vin8003.atlassian.net/browse/OE-366) · [snapshot](../tickets/OE-366.md)
- **Implementation:** EXTEND (optional echo of `Product.is_serialized` when the instance attribute exists)

Retailer product **list** and **detail** include top-level `is_serialized` only when that instance has the attribute. Detection uses `hasattr` / `getattr` on the instance — not serializer `Meta.fields` and not model `_meta`. If the attribute is missing (this stack: Product has no serialized-tracking column), the key is omitted. False stays false. Null stays null. This is a field echo, not a serial-number / IMEI inventory model (F-0020 / OE-189 stay later).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| Product list identity (`id` / `name` / `barcode`) | EXISTING |
| Optional `is_serialized` on list/detail (`to_representation`) | EXTEND |
| `ProductSearchSerializer` Meta | EXISTING — do not change |
| POS `?no_page=true` row dict | EXISTING — do not add `is_serialized` |
| Product `is_serialized` column / serial ledger | Out of scope |

## API

| Method | Path | Who | `is_serialized` |
|--------|------|-----|-----------------|
| GET | `/api/products/` | Authenticated retailer | Present only if `hasattr(product, 'is_serialized')` |
| GET | `/api/products/<id>/` | Authenticated retailer | Same echo as list |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Additive via shared list serializer |

Missing attribute → key omitted. Attribute `None` → `null`. False stays false. Do not invent True.

Unauthenticated retailer list → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

`OptionalIsSerializedMixin` reads the already-loaded product row. The echo adds no extra product query.

## Not in this change

Serial-number ledger, IMEI / serialized inventory writes, search Meta, POS `products/views.py` row keys, create/update serializers, cart, returns, purchase invoice, customers, orders, inventory.adjust, pack write, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live production hosts.
