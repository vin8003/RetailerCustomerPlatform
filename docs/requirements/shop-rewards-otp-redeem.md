# Shop rewards and OTP redeem

- **Ticket:** [OE-220](https://vin8003.atlassian.net/browse/OE-220) · backlog `F-0107` · subtask [OE-273](https://vin8003.atlassian.net/browse/OE-273) (`S-0107A`) · [snapshot](../tickets/OE-220.md)
- **Implementation:** EXTEND (`RetailerRewardConfig` + `CustomerLoyalty` + `Order.discount_from_points`)
- **Depends on:** [customer-profile-order-history.md](customer-profile-order-history.md) (F-0105 / OE-212 phone lookup)

One wallet per customer + shop location (`CustomerLoyalty`). Do not add `restaurant_points` or a second balance table.

This change is **slice B (OTP redeem)** only. Earn-on-sale already runs on POS finalize and app `delivered` via `Order.award_loyalty_points()`.

## EXISTING / EXTEND / NEW / SKIPPED

| Piece | Status |
|-------|--------|
| `RetailerRewardConfig` earn + redeem caps | EXISTING |
| `CustomerLoyalty` / `LoyaltyTransaction` | EXISTING — one wallet |
| App checkout `use_reward_points` | EXISTING; **EXTEND** — OTP required when flag is on |
| POS finalize earn | EXISTING |
| POS finalize redeem | **MISSING / follow-on** — no FE rebuild in this slice |
| `otp_required_for_redeem` | EXTEND |
| Loyalty redeem OTP (SMS to registered mobile) | NEW — reuses `generate_otp` / `send_sms_otp`, not login `OTPVerification` |
| Staff redeem on a pending order | EXTEND |
| Chain A-earn / B-burn policy | **MISSING / follow-on** — not invented |
| Restaurant visit earn | **MISSING / follow-on** — same wallet later; no second balance |
| F-0007 operation password | **MISSING** — not in tree; OTP is the sensitive gate |

## API

| Method | Path | Who | Behavior |
|--------|------|-----|----------|
| PUT | `/api/retailer/reward-config/` | Shop owner | May set `otp_required_for_redeem`. Customer JWT **403**. Own row only. |
| POST | `/api/customer/loyalty/redeem-otp/` | Customer | Sends OTP to the caller's registered mobile for that retailer. Response never includes the code. |
| POST | `/api/customer/retailer/loyalty/redeem-otp/` | Owner / staff with `orders.update` + `rewards` module | Sends OTP to the org customer. Cross-tenant **404**. Customer JWT **403**. |
| POST | `/api/orders/place/` | Customer | `use_reward_points` + OTP mode on without `redeem_otp` → **400**, no order, wallet unchanged. Valid OTP burns and sets `discount_from_points`. |
| POST | `/api/customer/retailer/loyalty/redeem/` | Owner / staff with `orders.update` | Applies redeem to a **pending** order in the org. OTP required when flag is on. Cross-tenant **404**. Unauthorized **403**, order and wallet unchanged. |

## Security

- OTP secrets are not returned in JSON and must not be logged.
- A used OTP cannot be reused. Failed OTP does not decrease points.
- Tenant filter is the caller's org locations (`get_order_for_retailer`).
- Redeem mutates order totals — reuse `orders.update` (catalog has no `rewards.redeem`).

## Not in this change

Chain-wide program policy, restaurant visit earn, POS checkout burn / FE redeem UI, campaigns, second wallet, live `*.ordereasy.win`.
