# Optional case quantity on product reads

- **Implementation:** EXTEND (echo `case_qty` only when the Product model has that field)
- **Related:** [parent-child-pack-skus.md](parent-child-pack-skus.md), [pack-children-reads.md](pack-children-reads.md)

Retailer product **list**, **detail**, and **search** serializers include top-level `case_qty` when the Product model defines a `case_qty` field. The key is injected in `to_representation`. It is **not** declared on serializer `Meta.fields` (a Meta listing would fail if the column is absent).

This repo's Product model does not currently define `case_qty`. Until a later migration adds the column, payloads omit the key. An instance attribute alone is not enough.

JSON shape matches existing quantity fields (`json_qty`): null → `0`, whole Decimal → int, fractional Decimal → float.

This is a read echo, not a write path, not a case-break engine, and not a POS `no_page` hand-built row.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.case_qty` model field / migration | Out of scope (may be absent) |
| List / detail / search `Meta.fields` | EXISTING, unchanged — do not add `case_qty` |
| `case_qty` on list / detail / search when the model field exists | EXTEND |
| Create / update serializers, POS `no_page` dict, cart, orders | Out of scope |

## API

| Method | Path | Who | `case_qty` |
|--------|------|-----|------------|
| GET | `/api/products/` | Authenticated retailer | Present only if model field exists |
| GET | `/api/products/<id>/` | Authenticated retailer | Same |
| GET | `/api/products/search/` | Authenticated retailer | Same |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Same rule via shared list/detail serializers |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Same rule via shared search serializer |

Unauthenticated retailer list/search/detail → **401**. Customer on retailer routes → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Model/migration for `case_qty`, serializer Meta, POS `no_page` hand-built payload, create/update writes, pack write, inventory.adjust, FE, Jira Done, live `*.ordereasy.win`.
