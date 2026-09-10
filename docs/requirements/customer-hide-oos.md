# Hide out-of-stock products in the customer app

- **Ticket:** [KAN-63](https://vin8003.atlassian.net/browse/KAN-63) · [snapshot](../tickets/KAN-63.md)
- **App:** customer (`customer_ordereasy_njs`) via public product APIs. Retailer app is unchanged.

Customer listings hide products that track inventory and have `quantity <= 0`. Products with `track_inventory=False` stay visible. Restocking (`quantity > 0`) makes the product appear again with no extra flag.

Applies to customer catalog, search, home lanes (featured, seasonal, deals, budget, trending, new arrivals, best selling, buy again, recommended), and related pack sizes (`group_variants` on product detail). Customer listing views wrap `hide_oos_for_customer`, which filters `Product.objects` for that request. Direct product-detail URLs may still load an OOS item so a leftover cart/wishlist link does not 404.

Retailer `GET /api/products/` and retailer search still return OOS rows.
