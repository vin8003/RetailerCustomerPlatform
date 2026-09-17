# Discounted price on retailer product search

- **Ticket:** [OE-298](https://vin8003.atlassian.net/browse/OE-298) · [snapshot](../tickets/OE-298.md)
- **Implementation:** EXTEND (echo existing `Product.discounted_price` on search)
- **Related:** [search-product-group.md](search-product-group.md) (OE-295), [search-is-seasonal.md](search-is-seasonal.md) (OE-294), [search-original-price.md](search-original-price.md) (OE-293), [search-category-name.md](search-category-name.md) (OE-291), [search-barcode.md](search-barcode.md) (OE-290), [search-pos-brand-name.md](search-pos-brand-name.md) (OE-287), [app-vs-pos-prices.md](app-vs-pos-prices.md) (OE-106)

Retailer product search includes top-level `discounted_price` with the same value already returned by list/detail (`Product.discounted_price`, a property that returns `Product.price`). This is a field echo, not price write.

`discounted_price` is a model `@property`, not a DB column. List/detail already declare it as a read-only `DecimalField`. Search uses the same declaration (not a `SerializerMethodField`). No extra `select_related`.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `discounted_price` on list / detail serializers | EXISTING |
| `discounted_price` on POS `?no_page=true` row dict | EXISTING (`p.discounted_price or p.price`) |
| `discounted_price` on `ProductSearchSerializer` | EXTEND (OE-298) |
| Price write APIs | Out of scope |

## API

| Method | Path | Who | `discounted_price` |
|--------|------|-----|--------------------|
| GET | `/api/products/search/` | Authenticated retailer | Same as list/detail (`Product.discounted_price`) |
| GET | `/api/products/` | Authenticated retailer | EXISTING |
| GET | `/api/products/<id>/` | Authenticated retailer | EXISTING |
| GET | `/api/products/?no_page=true` | Authenticated retailer | EXISTING (`or price`) |
| GET | `/api/products/retailer/<id>/` (public) | Customer / anonymous | EXISTING |
| GET | `/api/products/retailer/<id>/search/` (public) | Customer / anonymous | Additive via shared search serializer (same value as public list) |

`Product.price` is required, so a persisted SKU never has a null `discounted_price`. List/detail and search go through `ChannelPriceRepresentationMixin`, which rewrites `discounted_price` to the channel selling price when the key is present. If the property were null, the mixin surfaces `resolve_channel_price` (store `price` for retailer APIs; `app_price` or `price` for public/app). POS `no_page` uses `discounted_price or price` (store list only). Search mirrors list/detail; retailer search vs POS is Decimal-equal.

Public / app channel still hides `app_price` and rewrites selling fields (including `discounted_price`) to the app list. Retailer / store channel keeps store `discounted_price` and still exposes `app_price`.

Unauthenticated retailer search → **401**. Customer → **403**. Tenant B cannot read tenant A's SKU.

## Not in this change

Price write, margin invent, GST, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, FE, Jira Done, live `*.ordereasy.win`.
