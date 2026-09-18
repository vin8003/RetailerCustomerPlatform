# Optional `is_weighted` on product reads

- **Implementation:** EXTEND (echo `Product.is_weighted` only when the model field exists)
- **Related:** [search-is-active.md](search-is-active.md) (OE-300)

List, detail, and search product serializers may include top-level `is_weighted` when `Product` has that model field. This slice does **not** add a column, migration, or `Meta.fields` entry. `ModelSerializer` Meta binding would crash if the field is listed but absent.

When the field is missing, the key is omitted. When the field exists, `true` and `false` both stay in the payload (`false` is not omitted).

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.is_weighted` model field / migration | Out of scope (may be absent) |
| `is_weighted` on list / detail / search `Meta.fields` | Avoided on purpose |
| `is_weighted` on list / detail / search representation | EXTEND — only if the model field exists |
| Weighted write / admin / FE / live hosts | Out of scope |

## API

| Method | Path | Who | `is_weighted` |
|--------|------|-----|---------------|
| GET | `/api/products/` | Authenticated retailer | Present only if the model field exists |
| GET | `/api/products/<id>/` | Authenticated retailer | Same |
| GET | `/api/products/search/` | Authenticated retailer | Same |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same — shared `ProductListSerializer` |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Same — shared list serializer |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Same — shared search serializer |

Unauthenticated retailer search → **401**.

## Not in this change

Model field, migration, serializer `Meta.fields`, write/admin, FE, GST, pack write, inventory.adjust, live `*.ordereasy.win`. Tests use dummy hosts (`example.test`) only.
