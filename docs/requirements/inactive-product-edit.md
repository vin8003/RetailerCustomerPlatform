# Inactive products remain editable

- **Ticket:** [KAN-62](https://vin8003.atlassian.net/browse/KAN-62) · [snapshot](../tickets/KAN-62.md)
- **App:** `retailer_ordereasy_njs` · API this repo

An **inactive** product can be edited/updated without first flipping it active.

If PATCH is rejected when inactive, that is a backend gate — do not ship a UI-only workaround that still fails the API.
