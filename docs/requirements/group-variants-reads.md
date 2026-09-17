# Group variants on retailer list / search / POS

- **Ticket:** [OE-192](https://vin8003.atlassian.net/browse/OE-192) · backlog `F-0018` (thin slice) · [snapshot](../tickets/OE-192.md)
- **Implementation:** EXTEND (reuse detail `group_variants`)
- **Depends on:** [app-vs-pos-prices.md](app-vs-pos-prices.md)
- **Related:** [search-product-group.md](search-product-group.md) (OE-295 top-level `product_group` echo)

When `product_group` is set, retailer/POS **list**, **search**, and **`no_page`** include the same sibling `group_variants` rows that product detail already returned. Empty group (unset, or no other active/available siblings) → `[]`.

This is not a size/color matrix. There is no variant SKU generator.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `Product.product_group` + detail `get_group_variants()` | EXISTING |
| Sibling shape (`id`, `name`, `unit`, `price`, `quantity`, plus detail extras) | EXISTING |
| Channel price on variant `price` | EXISTING (OE-106) |
| `group_variants` on retailer list, search, POS `no_page` | EXTEND |
| One shop-scoped sibling cache for multi-product reads | EXTEND |
| Size/color matrix generator, variant SKU invent | Out of scope |

## API

| Method | Path | Who | `group_variants` |
|--------|------|-----|------------------|
| GET | `/api/products/<id>/` | Authenticated retailer | Siblings when `product_group` set; else `[]` |
| GET | `/api/products/` | Authenticated retailer | Same (paginated list) |
| GET | `/api/products/?no_page=true` | Authenticated retailer | Same (POS catalog) |
| GET | `/api/products/search/` | Authenticated retailer | Same |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | Same field via shared list serializer |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Same field via shared search serializer |

Sibling rows are same-shop, `is_active=True`, and `is_available=True`. The current SKU is omitted. List/search use one `product_group IN (...)` cache so the helper does not query per product. POS `no_page` uses the same cache on the hand-built payload.

Unauthenticated → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU (**404** on detail; absent from list/search/POS). Same `product_group` name on another shop is not a sibling.

## Not in this change

Full F-0018 size/color matrix generator, variant SKU invent, OE-102, #103, notify, FE redesign, Jira Done, live production hosts.
