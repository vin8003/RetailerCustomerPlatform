# Optional locality on retailer customer detail

- **Ticket:** [OE-361](https://vin8003.atlassian.net/browse/OE-361) · [snapshot](../tickets/OE-361.md)
- **Implementation:** EXTEND (optional echo of `locality` when the attribute exists)

Retailer **customer detail** includes top-level `locality`. If the mapping, profile, user, or (when the model declares the field) default address has a `locality` attribute, the stored value is echoed. If the attribute is missing (this stack: no customer/mapping/address `locality` column), or the value is null, the payload is `null`. Empty string stays empty. This is a field echo, not a new address model.

Customer **list** does not include `locality`. List is a hot path and is contested by OE-305; do not add a per-row address lookup there.

## EXISTING / EXTEND / NEW

| Piece | Status |
|-------|--------|
| `RetailerCustomerDetailSerializer` identity / notes / credit | EXISTING |
| Optional `locality` on customer detail | EXTEND (OE-361) |
| `RetailerCustomerListSerializer` | EXISTING (OE-305 owns list scalars) — do not add `locality` |
| `CustomerAddress.locality` / mapping locality column | Out of scope |

## API

| Method | Path | Who | `locality` |
|--------|------|-----|------------|
| GET | `/api/customer/retailer/details/<customer_id>/` | Authenticated retailer | `getattr(mapping/profile/user/default address, 'locality', None)` |
| GET | `/api/customer/retailer/list/` | Authenticated retailer | **omitted** — list hot path / OE-305 |

Missing attribute → `null`. Null stays null. Empty stays empty. Do not invent a locality.

When no candidate model declares `locality`, the detail view does not query `CustomerAddress` to look for it.

Unauthenticated → **401**. Customer JWT → **403**. Tenant B cannot read tenant A's mapping-only fields as tenant A.

## Not in this change

List serializer (OE-305), address model / migration, wishlist (OE-343), CRM write, FE, timeline/OFD/khata/UPI/slots, inventory.adjust, pack write, Jira Done, live `*.ordereasy.win`.
