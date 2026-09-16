# Suppliers (vendor master)

- **Ticket:** [OE-100](https://vin8003.atlassian.net/browse/OE-100) · backlog `F-0041` · [snapshot](../tickets/OE-100.md)
- **Implementation:** EXTEND (`retailers.Supplier` + existing `products.SupplierLedger`)
- **Depends on:** [retailer-organization.md](retailer-organization.md) (org tenancy) and [shop-staff-roles.md](shop-staff-roles.md) (`purchasing.terms`)

One vendor master. Do not invent a second supplier / vendor table. Ledger rows stay on `SupplierLedger`. Full PO / GRN three-way match is [OE-102](https://vin8003.atlassian.net/browse/OE-102), not this slice.

## EXISTING / EXTEND / NEW

| Piece | Kind |
|-------|------|
| `retailers.Supplier` (contacts, optional `gst_number`, `is_active`, shop FK) | EXISTING |
| `GET/POST /api/products/erp/suppliers/` and item routes | EXISTING |
| `products.SupplierLedger` + purchase-invoice create | EXISTING |
| `PurchaseInvoice.supplier` as the current inward counterparty | EXISTING — no `PurchaseOrder` model yet |
| `payment_terms` on `Supplier` | EXTEND |
| Duplicate non-blank GSTIN flagged per **org** (`gstin_duplicate`) | EXTEND |
| Org-unique non-blank GSTIN DB constraint (`uniq_org_supplier_nonblank_gstin`) | EXTEND — denormalized `Supplier.organization`; blank/null GSTIN stored as `''` and may repeat. Concurrent insert maps `IntegrityError` to the same 400 |
| Reads scoped on `Supplier.organization`, falling back to `retailer__organization` for NULL denorm | EXTEND — the denorm is the same column as the unique constraint, so the app duplicate check and the DB cover the same rows. `Supplier.save()` keeps it in step and migration 0028 backfilled, but a bulk write or a lazily provisioned org can still leave it NULL, and those rows stay org-scoped through `retailer` |
| `purchasing.terms` for payment-terms writes (**403**) | EXTEND (catalog v10) |
| Inactive supplier blocked on **new** purchase-invoice create / supplier change | EXTEND |
| `GET /api/products/erp/suppliers/?is_active=true` picker filter | EXTEND — hook for OE-102 PO picker |
| `assert_supplier_selectable_for_new_purchase` | EXTEND — call from OE-102 PO create |
| Org-scoped list / retrieve / mutate (404 deny cross-tenant) | EXTEND (was shop-owner `RetailerProfile.user` only) |
| Bank payment initiation, buyer analytics, FE redesign | OUT |

## API

| Method | Path | Behavior |
|--------|------|----------|
| POST | `/api/products/erp/suppliers/` | Create. `gst_number` optional (`null` / `""` / omitted all store blank). Blank GSTIN may repeat. Duplicate non-blank GSTIN in the same org → **400** + `gstin_duplicate` (app check and DB unique). Non-empty `payment_terms` requires `purchasing.terms`. Whitespace-only `payment_terms` → **400**. Terms are trimmed. |
| GET | `/api/products/erp/suppliers/` | Same-org suppliers. `?is_active=true` hides inactive (picker). |
| PATCH | `/api/products/erp/suppliers/<id>/` | Echoing current `payment_terms` (after trim) is allowed. Changing terms without `purchasing.terms` → **403**, row unchanged. Whitespace-only `payment_terms` → **400**, row unchanged. |
| POST | `/api/products/erp/purchase-invoices/` | Inactive `supplier` → **400**. Cross-org supplier → **400**. Existing invoice may keep a supplier later marked inactive. |

GSTIN is stored as `gst_number` (uppercase). Format must match `22AAAAA0000A1Z5` when provided.

## Roles

- Catalog version includes `purchasing.terms`.
- System **Admin** bootstrap includes every catalog code (this one too).
- System **Cashier** bootstrap stays empty — cannot change payment terms.
- Org **owner** is implicit admin.

## OE-102 hook

There is no PO/GRN create path yet. When OE-102 adds PO create:

1. Filter pickers with `active_suppliers_for_org(org)` or `GET .../erp/suppliers/?is_active=true`.
2. Call `retailers.suppliers.assert_supplier_selectable_for_new_purchase(supplier)` before save.
3. Reuse the same org check (`assert_supplier_in_org`).

Purchase-invoice create is the current gate.

## Query budgets

`assertNumQueries` on the supplier endpoints (dummy DB, `retailers/tests/test_suppliers_oe100.py`):

| Endpoint | Budget |
|----------|--------|
| `GET /erp/suppliers/` | **3** — flat at 8 rows |
| `POST /erp/suppliers/` | **6** |
| `GET /erp/suppliers/<id>/` | **2** |
| `PATCH /erp/suppliers/<id>/` (payment terms + audit) | **8** |

The caller's organization is resolved once per request and passed to the
serializer and the audit writer.

`GET /erp/purchase-invoices/` joins `supplier` (the list exposes
`supplier_name`), asserted in `products/tests/test_purchase_invoice_supplier_gate_oe100.py`:

| Part | Budget |
|------|--------|
| Fixed, page not empty | **4** — caller retailer for the queryset, page count, invoice page, caller retailer for the serializer context |
| Per invoice | **4** — `refund_amount` and `net_amount` each aggregate `purchase_return`, `is_returned` runs `exists()`, plus the nested items page |

The per-invoice figure is flat in the number of distinct suppliers on the page;
the four remaining per-invoice reads are the invoice's own children and are not
part of this slice.

## Security

- Tenant A cannot list, read, patch, or delete tenant B's suppliers (**404**).
- Customers cannot manage suppliers (**403**).
- Payment-terms mutations are audited (`OrgAuditLog` `object_type=supplier`).

## Not in this change

PO/GRN three-way match, bank payment initiation, buyer analytics, FE redesign, Jira Done, live `*.ordereasy.win`.
