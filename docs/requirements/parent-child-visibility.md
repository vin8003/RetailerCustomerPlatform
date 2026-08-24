# Parent-child product visibility (customer app)

- **Status:** Implemented
- **Ticket:** [KAN-49](https://vin8003.atlassian.net/browse/KAN-49) · [snapshot](../tickets/KAN-49.md)
- **Apps:** `RetailerCustomerPlatform` · `retailer_ordereasy_njs`

Bulk parent SKUs (e.g. 30 kg bag) and fractional child packs (500 g, 1 kg) share quantity and `track_inventory` via `Product.sync_fractional_inventories()`. **`is_available` is not copied** from parent to children.

## Rules

- Retailers toggle **Show on Customer App** on the **parent bulk SKU** in the retailer product form.
- Hiding the parent does **not** hide child packs that remain `is_available=True`.
- Child packs keep independent customer-app visibility.
- Quantity and inventory tracking still sync parent → children as before.

## Retailer UI

The visibility toggle lives on the parent bulk SKU row in `ProductForm`, not on each child pack.
