# Retailer and customer API versioning

- **Ticket:** [OE-182](https://vin8003.atlassian.net/browse/OE-182) · backlog `F-0006` · [snapshot](../tickets/OE-182.md)
- **Implementation:** EXTEND (DRF auth + org-scoped keys/scopes/rate limits; no new gateway process)
- **Depends on:** [OE-97 organization](retailer-organization.md), [OE-98 staff roles](shop-staff-roles.md)
- **App:** Backend `RetailerCustomerPlatform`. Optional retailer settings UI later — **no** customer-app staff-admin screens.

## Problem

DRF served JWT apps but was not a productized partner API platform (no keys, scopes, or version prefix).

## What shipped

| Piece | Detail |
|-------|--------|
| Tenant key | `Organization` (org-scoped `OrgApiKey`) |
| Scopes | Versioned catalog in `retailers/api_scopes.py` (`API_SCOPE_CATALOG_VERSION`) |
| Auth | `Authorization: Api-Key <raw>` or `X-Api-Key` via `OrgApiKeyAuthentication` |
| Rate limit | `OrgApiKeyRateThrottle` (`api_key` = 600/hour) |
| Versioning | `/api/v1/partner/*`; JWT aliases `/api/v1/retailer/`, `/api/v1/customer/`; policy at `GET /api/v1/` |
| Audit | `OrgApiKeyAudit` on grant / revoke / scope change |
| Staff gate | `api_keys.manage` added to OE-98 permission catalog (owner = implicit admin) |

## Partner scopes (deny-by-default)

| Code | Meaning |
|------|---------|
| `partner.org.read` | Read org metadata bound to the key |
| `partner.org.write` | Rename the key's organization |
| `partner.locations.read` | List/read shop locations for the key's org |

Unknown scopes are rejected on key create/update.

## API

### JWT management (retailer app / staff — unchanged auth)

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| GET | `/api/retailer/org/<id>/api-scopes/` | Same-tenant | Versioned partner scope catalog |
| GET/POST | `/api/retailer/org/<id>/api-keys/` | `api_keys.manage` | List / create (raw secret once on create) |
| GET/PATCH/DELETE | `/api/retailer/org/<id>/api-keys/<key_id>/` | `api_keys.manage` | Read / change scopes / soft-revoke |

Also available under `/api/v1/retailer/...` (alias). Unversioned paths remain for `retailer_ordereasy_njs`.

### Partner key-authenticated (v1)

| Method | Path | Scope | Behavior |
|--------|------|-------|----------|
| GET | `/api/v1/` | public | Version + sunset policy |
| GET | `/api/v1/partner/scopes/` | any valid key | Scope catalog |
| GET/PATCH | `/api/v1/partner/org/` | read / write | Org bound to the key |
| GET | `/api/v1/partner/locations/` | `partner.locations.read` | Locations for key org only |
| GET | `/api/v1/partner/locations/<id>/` | `partner.locations.read` | Same-tenant location; else **403** |

Customer JWT routes keep `/api/customer/` and gain `/api/v1/customer/` alias. Customer app must not grow staff-admin screens.

## Security

- Deny-by-default scopes and staff permission `api_keys.manage`.
- Revoked key (`is_active=False`) is rejected on the **next** request (live DB check).
- Cross-tenant: key for org A cannot read/mutate org B (**403**, resource unchanged).
- Unauthenticated partner calls → **401**; missing scope → **403**.
- Raw key hashed at rest (`key_hash`); only `prefix` is stored in clear for lookup.

## Versioning policy

Breaking changes ship under a new prefix (`/api/v2/...`). **v1 remains until a documented sunset** (`API_VERSIONING['sunset']['v1']` in settings; currently `None`). See `GET /api/v1/`.

## Not in this change

- Partner catalog/order API productization (F-0118 / OE-250)
- Full shop audit product (OE-99 / F-0003) beyond API-key grant/revoke rows
- POS / catalog / stock / khata rewrites
- Forcing retailer/customer Next.js apps onto API keys
- Deploy / merge to `deploy/dev`
