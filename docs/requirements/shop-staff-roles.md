# Shop staff roles (RBAC)

- **Ticket:** [OE-98](https://vin8003.atlassian.net/browse/OE-98) · backlog `F-0002` · [snapshot](../tickets/OE-98.md)
- **Implementation:** NEW (`OrgRole`, `OrgStaffMembership`, `OrgStaffRoleAudit`)
- **Depends on:** [OE-97 retailer organization](retailer-organization.md) (`Organization` tenant)
- **App:** Backend `RetailerCustomerPlatform`. Optional tiny settings UI in `retailer_ordereasy_njs` only — no customer-app staff screens.

## Mapping to AUTH_USER_MODEL

Staff identity is **not** a parallel user table and **not** customer OTP.

| Concept | Storage |
|---------|---------|
| Login principal | `authentication.User` (`AUTH_USER_MODEL`), `user_type='retailer'` |
| Tenant | `retailers.Organization` |
| Named role | `retailers.OrgRole` (org-scoped; `permissions` = catalog codes) |
| Seat | `retailers.OrgStaffMembership` (unique per org+user) |
| Audit | `retailers.OrgStaffRoleAudit` on every grant / change / revoke |

Cashiers authenticate with password/JWT like shop owners. Customer OTP login is not used for staff.

## Permission catalog (versioned)

See `retailers/permissions_catalog.py` (`PERMISSION_CATALOG_VERSION`).

| Code | Meaning |
|------|---------|
| `org.update` | Rename / enable / disable organization |
| `roles.manage` | Create / edit named roles |
| `staff.manage` | Assign / change / revoke staff seats |
| `api_keys.manage` | Create / list / revoke org partner API keys (OE-182) |

Deny-by-default: unknown codes are rejected on role save. Org **owner** always has the full catalog (implicit admin). Bootstrap creates system **Admin** (all codes) and **Cashier** (empty) roles and an Admin membership for the owner.

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/retailer/org/<id>/permissions/` | Same-tenant | Versioned catalog |
| GET/POST | `/api/retailer/org/<id>/roles/` | GET same-tenant; POST `roles.manage` | List / create named roles |
| GET/PATCH | `/api/retailer/org/<id>/roles/<role_id>/` | PATCH `roles.manage` | Read / update role |
| GET/POST | `/api/retailer/org/<id>/staff/` | POST `staff.manage` | List / assign staff to a role |
| GET/PATCH/DELETE | `/api/retailer/org/<id>/staff/<id>/` | Mutations `staff.manage` | Change role / soft-revoke |
| PATCH | `/api/retailer/org/<id>/` | `org.update` | Unchanged OE-97 path; cashiers without the code get **403** |

Role checks read membership **on every request** (no JWT-embedded role cache), so role changes take effect on the next authorized call.

## Security

- Cross-tenant: org A callers cannot list or mutate org B roles/staff (**403**, resource unchanged).
- Unauthorized users (cashier without `staff.manage`, customers) cannot change another user's role.
- Removing / demoting the last owner via staff APIs is forbidden.
- Existing owner JWT/session continues to work; owner remains implicit admin.

## Not in this change

- OE-99 audit productization beyond grant/revoke rows, POS / catalog / stock / khata rewrites, multi-shop staff move (OE-203), customer-app staff UI.
- Partner open API keys/versioning: see [OE-182](OE-182.md) / [api-versioning.md](../requirements/api-versioning.md) (stacked on this work).
