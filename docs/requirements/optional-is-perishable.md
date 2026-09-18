# Optional `is_perishable` on product reads

- **Ticket:** [KAN-276](https://vin8003.atlassian.net/browse/KAN-276) · [snapshot](../tickets/KAN-276.md)
- **Implementation:** EXTEND (echo `Product.is_perishable` only when the model field exists)
- **Related:** [search-is-active.md](search-is-active.md) (OE-300), [product-batch-expiry.md](product-batch-expiry.md)

List, detail, and search product serializers may include top-level `is_perishable` when `Product` has that model field. This slice does **not** add a column, migration, or `Meta.fields` entry. `ModelSerializer` Meta binding would crash if the field is listed but absent.

When the field is missing, the key is omitted. When the field exists, `true` and `false` both stay in the payload (`false` is not omitted).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.is_perishable` model field / migration | Out of scope (may be absent) |
| `is_perishable` on list / detail / search `Meta.fields` | Avoided on purpose |
| `is_perishable` on list / detail / search representation | EXTEND — only if the model field exists |
| Perishable write / admin / FE / live hosts | Out of scope |

## API

| Method | Path | Who | `is_perishable` |
|--------|------|-----|-----------------|
| GET | `/api/products/` | Authenticated retailer | Present only if the model field exists |
| GET | `/api/products/<id>/` | Authenticated retailer | Same |
| GET | `/api/products/search/` | Authenticated retailer | Same |

Unauthenticated retailer search → **401**.

## Not in this change

Model field, migration, serializer `Meta.fields`, write/admin, FE, GST, pack write, inventory.adjust, live `*.ordereasy.win`. Tests use dummy hosts (`example.test`) only.
