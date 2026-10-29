# data-testid contract (OE-367 / OE-369)

The specs find controls only through these ids (plus a few visible labels). Renaming or
removing one breaks the e2e check on the app's PR. Add new ids here in the same PR that uses them.
Ids are attributes only: no behaviour, style or copy changed (CASES.md §7, covered by the suite brief).

## Retailer app (`retailer_ordereasy_njs`)

| id | where | used by |
|---|---|---|
| `login-username`, `login-password`, `login-submit` | `/login` | all retailer journeys |
| `login-error` | `/login` failure toast (sonner `testId`) | R-AUTH3, R-AUTH4 |
| `pos-search` | POS barcode/search input | A1–A6 |
| `pos-unknown-barcode` | Quick add modal heading for an unknown barcode | A4 |
| `pos-cart-line` (`data-barcode`), `pos-cart-line-qty` | POS cart line, its qty | A1–A6 |
| `pos-total` | POS bill total | A1–A6 |
| `pos-customer-mobile`, `pos-customer-name` | POS customer attach | A2, A3, A5 |
| `pos-pay-cash`, `pos-pay-upi`, `pos-pay-credit`, `pos-pay-split` | payment mode | A1–A3, A5, A6 |
| `pos-split-cash`, `pos-split-upi`, `pos-split-credit`, `pos-split-mismatch` | split payment | A3 |
| `pos-checkout-complete`, `pos-complete-bill`, `pos-paid-total`, `pos-new-bill` | bill completion | A1–A6 |
| `customer-current-balance`, `customer-credit-limit` | customer detail (khata) | C1–C5 |
| `record-payment-open`, `record-payment-amount`, `record-payment-submit` | record khata payment | C1–C4 |
| `order-status` | order detail status badge | B2–B4 |
| `order-total`, `order-slot` | order detail total, slot | B1–B4, T2 |
| `order-status-next-<status>` | next-status buttons (e.g. `order-status-next-confirmed`) | B2–B4 |
| `order-confirm-submit`, `order-dispatch-submit` | confirm / dispatch dialogs | B2, B4 |
| `khata-panel` | customer detail Stats Overview card (C5 scopes its "no R1 numbers" check to it) | C5 |
| `signup-username`, `signup-email`, `signup-phone`, `signup-password`, `signup-confirm-password`, `signup-submit` | `/signup` | R-AUTH1 |
| `verification-banner` | dashboard pending-approval banner | R-AUTH1, R-AUTH2 |
| `verification-card` (`data-username`), `verification-approve` | admin `/dashboard/admin/verifications` | R-AUTH2 |
| `forgot-identifier`, `forgot-send`, `reset-code`, `reset-new-password`, `reset-confirm-password`, `reset-submit` | `/forgot-password` | R-AUTH5 |
| `profile-edit`, `profile-shop-name`, `profile-city`, `profile-save`, `profile-logout` | `/dashboard/profile` | R-AUTH6 |

## Customer app (`customer_ordereasy_njs`)

| id | where | used by |
|---|---|---|
| `customer-login-phone`, `customer-login-password`, `customer-login-submit` | `/login` password login | all customer journeys |
| `add-to-cart-<productId>`, `cart-qty-<productId>`, `cart-increment-<productId>` | product card cart control | B1, T2 |
| `cart-checkout` | cart page CTA | B1, T2 |
| `slot-picker-open`, `slot-summary`, `slot-day-<YYYY-MM-DD>`, `slot-option` (`data-slot-start` = local ISO), `slot-confirm` | fulfillment slot picker | B1, T2 |
| `checkout-address-<addressId>`, `checkout-pay-cod`, `checkout-total`, `checkout-place-order` | checkout | B1 |
| `orders-filter-<status>` (`orders-filter-all` for All) | My Orders filter chips | B4 |
| `order-card` (`data-order-id`), `order-card-status` | My Orders card, its status | B1–B4, T1, F7 |
| `order-status-label`, `order-total`, `order-slot` | order detail | B1–B4, T2 |
| `customer-login-error` | `/login` error text | C-AUTH3 |
| `customer-signup-email`, `-phone`, `-password`, `-confirm`, `-submit`, `-error` | `/signup` | C-AUTH1 |
| `verify-email-otp`, `-submit`, `-error`, `-success` | `/verify-email` | C-AUTH1, C-AUTH2 |
| `customer-forgot-email`, `-send`, `-error`, `-success`; `customer-reset-otp`, `-password`, `-confirm`, `-submit` | forgot / reset password | C-AUTH4 |
| `profile-first-name`, `profile-last-name`, `profile-save`; `profile-name`, `profile-logout` | profile edit; profile page | C-AUTH5 |
