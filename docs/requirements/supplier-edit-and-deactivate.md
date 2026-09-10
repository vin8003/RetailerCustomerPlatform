# Supplier edit and safe deactivation

- **Ticket:** [KAN-78](https://vin8003.atlassian.net/browse/KAN-78) · [snapshot](../tickets/KAN-78.md)
- **App:** `retailer_ordereasy_njs` Khata / purchases · API this repo (`Supplier.is_active`)

Retailers can **edit** supplier details and **deactivate** a supplier without losing khata, purchases, payments, or returns.

## Rules

- **Edit** is allowed while inactive. Do not require activating first (same as inactive products).
- **Deactivate** is `PATCH { "is_active": false }`. Always allowed, including when invoices or ledger exist. **Reactivate** is `PATCH { "is_active": true }`.
- **Khata list and ledger** still show inactive suppliers (Inactive badge). Payments and invoice-scoped purchase returns remain allowed.
- **New purchases** and **changing an invoice to a different inactive supplier** are rejected by the API. Pickers request `?is_active=true`.
- **Hard DELETE** is blocked if any purchase invoices, ledger entries, or purchase returns exist. Tell the client to deactivate instead. Unused suppliers may still be deleted via API; the retailer UI does not expose Delete.
- Phone remains optional (KAN-56). Do not require GST or persist email for this flow.

## Picker vs directory

| Surface | Inactive suppliers |
|---------|--------------------|
| Khata list, supplier ledger | Shown |
| New purchase picker | Hidden |
| Purchase-edit picker | Hidden, except the invoice’s current supplier (kept selected) |
| Standalone purchase-return picker | Hidden |
| Return from an existing invoice | Allowed even if the supplier is inactive |
