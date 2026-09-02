# Retailer organization (tenant parent)

- **Ticket:** [OE-97](https://vin8003.atlassian.net/browse/OE-97) · backlog `F-0001` · [snapshot](../tickets/OE-97.md)
- **Implementation:** EXTEND (`retailers.Organization` + FK on `RetailerProfile`)
- **App:** Backend `RetailerCustomerPlatform`. Settings may show `organization_name` from profile API; no chain UI forced on single-shop tenants.

## Model

| Concept | Record | Notes |
|---------|--------|-------|
| Tenant parent | `Organization` | `name`, `owner`, `is_active` |
| Shop / location | `RetailerProfile` | Operational shop; GSTIN, UPI, receipt footer stay here |
| Mapping (v1) | 1:1 | Existing kirana shops get an implicit org via migration backfill + signup/create |

Location stays **implicit** for existing single-shop tenants: APIs keep resolving the shop via `user → RetailerProfile`. Multi-location (OE-185) and staff RBAC (OE-98) are out of scope for this ticket.

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/retailer/org/` | Authenticated retailer | Caller's org (creates implicit 1:1 if missing) |
| POST | `/api/retailer/org/` | Shop owner (staff-admin) | Create org, attach existing shop as location 1 |
| GET | `/api/retailer/org/<id>/` | Same-tenant retailer | Own org only; cross-tenant → **403** |
| PATCH | `/api/retailer/org/<id>/` | Org owner (staff-admin) | Update `name` / `is_active`; non-admin → **403**, resource unchanged |
| GET | `/api/retailer/profile/` | Retailer | Includes `organization_id`, `organization_name`, `organization_is_active` |

Existing retailer profile APIs continue to work with the implicit org. Until OE-98, **staff-admin = organization owner**.

## Security

- Deny-by-default across tenants: org A data is never returned on org B's authenticated org APIs.
- `Organization.is_active=False` blocks **new** retailer login sessions (`403`); rows and history are retained.
- Unauthenticated org calls → `401`. Wrong role / non-admin mutate → `403` without changing the resource.

## Not in this change

- OE-98 shop staff roles, OE-182 API versioning, POS / catalog / stock / khata rewrites, second shop table, competitor branding.
