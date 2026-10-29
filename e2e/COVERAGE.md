# Feature coverage — Playwright e2e

One row per feature. Status: *covered* = at least one spec asserts the outcome (regression guards and a `test.fixme` linked to a bug count); *slice-PR pending* = owned by an open phase 3–5 slice PR; *not started* = no spec and no owner yet.
Update the row in the PR that adds or removes a spec. Phases: 2 auth & account · 3 POS camera, delivery fee, bundles · 4 catalog, offers, inventory · 5 everything else.
Phase 3–5 rows are owned by their phase slice (separate PRs); each slice updates its rows' coverage.

## Totals

| phase | scope | covered | slice-PR pending | not started | total |
|---|---|---|---|---|---|
| 2 | auth & account | 10 | 0 | 4 | 14 |
| 3 | POS camera scan, distance delivery fee, bundles | 2 | 3 | 0 | 5 |
| 4 | catalog, offers/coupons, inventory | 4 | 8 | 0 | 12 |
| 5 | orders edge cases, khata, reports, settings, app pages | 5 | 22 | 0 | 27 |
| **all** | | **21** | **33** | **4** | **58** |

## Features

| area | feature | routes / endpoints (`/api/` omitted) | current coverage | status | target phase |
|---|---|---|---|---|---|
| Auth (retailer) | Retailer signup → pending approval banner | /signup · auth/retailer/signup/ | auth-retailer.spec.ts › R-AUTH1 | covered | 2 |
| Auth (retailer) | Admin approves a pending retailer | /dashboard/admin/verifications · retailer/admin/verifications/, …/<id>/action/ | auth-retailer.spec.ts › R-AUTH2 | covered | 2 |
| Auth (retailer) | Retailer login (success + wrong password + customer creds refused) | /login · auth/retailer/login/ | auth-retailer.spec.ts › R-AUTH3, R-AUTH4 (success: every retailer journey) | covered | 2 |
| Auth (retailer) | Retailer password reset via phone OTP | /forgot-password · auth/retailer/password/forgot/, …/reset/ | auth-retailer.spec.ts › R-AUTH5 (test.fixme: bug OE-374) | covered | 2 |
| Account (retailer) | Shop profile edit persisted | /dashboard/profile · retailer/profile/, retailer/profile/update/ | auth-retailer.spec.ts › R-AUTH6 | covered | 2 |
| Account (retailer) | Admin rejects a retailer (reason shown) | retailer/admin/verifications/<id>/action/ | none | not started | 2 |
| Auth (customer) | Customer signup + email OTP verify | /signup, /verify-email · auth/customer/signup/, auth/verify-email/ | auth-customer.spec.ts › C-AUTH1 | covered | 2 |
| Auth (customer) | Unverified email cannot log in | /login · auth/customer/login/ | auth-customer.spec.ts › C-AUTH2 | covered | 2 |
| Auth (customer) | Customer login (success + wrong password) | /login · auth/customer/login/ | auth-customer.spec.ts › C-AUTH3 (success: every customer journey) | covered | 2 |
| Auth (customer) | Email password reset | /forgot-password · auth/password/email/forgot/, …/reset/ | auth-customer.spec.ts › C-AUTH4 | covered | 2 |
| Account (customer) | Profile edit persisted and shown | /profile · customer/profile/, customer/profile/update/ | auth-customer.spec.ts › C-AUTH5 | covered | 2 |
| Auth | Resend email OTP / phone OTP verify | auth/resend-email-otp/, auth/customer/verify-otp/, …/resend-otp/ | none | not started | 2 |
| Auth | Change password, logout, token refresh | auth/change-password/, auth/logout/, auth/token/refresh/ | none | not started | 2 |
| Auth | Google login (customer) | auth/customer/google-login/ | none (needs Firebase stub) | not started | 2 |
| POS | POS bills: UPI, khata, split, cash, unknown barcode | /dashboard/pos · products/erp/pos-checkout/ | pos.spec.ts › A1–A6 | covered | 3 (phase-3 slice) |
| POS | POS customer lookup / verify | products/erp/verify-pos-customer/, …/search-pos-customers/ | pos.spec.ts › A2, A3, A5 (partial) | covered | 3 (phase-3 slice) |
| POS | Mobile POS camera barcode scan (fake camera) | /dashboard/pos (mobile) | none | slice-PR pending | 3 (phase-3 slice) |
| Delivery | Distance-based delivery fee at checkout | retailer/geo-estimate/ · cart/summary/ | none | slice-PR pending | 3 (phase-3 slice) |
| Catalog | Bundles / product groups in cart and POS | products/product-groups/ | none | slice-PR pending | 3 (phase-3 slice) |
| Catalog | Product create / edit / delete | products/create/, <id>/update/, <id>/delete/ | none | slice-PR pending | 4 (phase-4 slice) |
| Catalog | Flat offer per unit; duplicate product name is a 400 | offers · products/<id>/update/ | fixme.spec.ts › F1, F5 (regression guards, OE-370/371) | covered | 4 (phase-4 slice) |
| Catalog | Bulk upload sessions and images | products/upload/…, upload/session/… | none | slice-PR pending | 4 (phase-4 slice) |
| Catalog | Categories and brands | products/categories/…, products/brands/… | none | slice-PR pending | 4 (phase-4 slice) |
| Catalog | Customer storefront sections and search | products/retailer/<id>/…, retailer/search/ | order.spec.ts › B1 (browse + add only) | covered | 4 (phase-4 slice) |
| Offers | Percentage cap, stackable and non-stackable offers | offers · cart/ | fixme.spec.ts › F2, F3, F4 (regression guards) | covered | 4 (phase-4 slice) |
| Offers | Offer + coupon discount shown once | cart/apply-coupon/ | fixme.spec.ts › F8 (regression guard) | covered | 4 (phase-4 slice) |
| Offers | Coupon apply/remove, available coupons | cart/apply-coupon/, remove-coupon/, offers/available-coupons/<id>/ | none | slice-PR pending | 4 (phase-4 slice) |
| Inventory | Stock write-off and inventory ledger | products/<id>/write-off/, erp/inventory-ledger/ | none | slice-PR pending | 4 (phase-4 slice) |
| Orders | Order lifecycle pending → delivered (both apps) | orders/place/, <id>/status/ | order.spec.ts › B1–B4 | covered | 5 (phase-5 slice) |
| Orders | IST midnight dates and next-day slots | orders/ · slot picker | time.spec.ts › T1, T2; fixme.spec.ts › F6 | covered | 5 (phase-5 slice) |
| Orders | Packed straight from Confirmed | orders/<id>/status/ | fixme.spec.ts › F9 (regression guard, OE-373) | covered | 5 (phase-5 slice) |
| Orders | Cancel, modify/confirm modification | orders/<id>/cancel/, modify/, confirm_modification/ | none | slice-PR pending | 5 (phase-5 slice) |
| Orders | Online payment submit/verify | orders/<id>/submit_payment/, verify_payment/ | none | slice-PR pending | 5 (phase-5 slice) |
| Orders | Order chat, notes, feedback, ratings | orders/<id>/chat/…, notes/, feedback/, rate-customer/ | none | slice-PR pending | 5 (phase-5 slice) |
| Returns | Return request | orders/<id>/return/, returns/ | none | slice-PR pending | 5 (phase-5 slice) |
| Khata | Record khata payment, limits, R1/R2 isolation | customer/retailer/payment/record/, ledger/<id>/ | khata.spec.ts › C1–C5 | covered | 5 (phase-5 slice) |
| Khata | Credit limit update, blacklist toggle | customer/retailer/credit-limit/update/<id>/, blacklist/toggle/ | none | slice-PR pending | 5 (phase-5 slice) |
| Loyalty | Loyalty points and redeem OTP | customer/loyalty/…, retailer/loyalty/redeem/ | none | slice-PR pending | 5 (phase-5 slice) |
| Customer | Addresses and wishlist | customer/addresses/…, wishlist/… | none | slice-PR pending | 5 (phase-5 slice) |
| Customer | Notifications, referrals | customer/notifications/…, referral/… | none | slice-PR pending | 5 (phase-5 slice) |
| Reports | Dashboard summary, daily sales, stats, demand insights | products/erp/dashboard/summary/, daily-sales-summary/, stats/ | none | slice-PR pending | 5 (phase-5 slice) |
| Settings | Operating hours, reward config, org settings | retailer/operating-hours/, reward-config/, org/ | none | slice-PR pending | 5 (phase-5 slice) |
| Partner API | Partner API v1 keys and endpoints | api/v1/partner/ | none | slice-PR pending | 5 (phase-5 slice) |
| Retailer app | Purchases | /dashboard/purchases · products/erp/purchases/… | none | slice-PR pending | 5 (phase-5 slice) |
| Retailer app | Suppliers | /dashboard/suppliers · products/erp/suppliers/… | none | slice-PR pending | 5 (phase-5 slice) |
| Retailer app | Display / print labels | /dashboard/display-labels, /dashboard/print-labels | none | slice-PR pending | 5 (phase-5 slice) |
| Retailer app | Reviews | /dashboard/reviews | none | slice-PR pending | 5 (phase-5 slice) |
| Retailer app | Product ledger | /dashboard/products/ledger · erp/inventory-ledger/ | none | slice-PR pending | 4 (phase-4 slice) |
| Retailer app | Order edit | /dashboard/orders/edit · orders/<id>/modify/ | none | slice-PR pending | 5 (phase-5 slice) |
| Retailer app | Offers new / edit | /dashboard/offers/new, /dashboard/offers/edit · offers/ | none | slice-PR pending | 4 (phase-4 slice) |
| Retailer app | Categories | /dashboard/categories · products/categories/… | none | slice-PR pending | 4 (phase-4 slice) |
| Customer app | Rewards | /rewards · customer/loyalty/… | none | slice-PR pending | 5 (phase-5 slice) |
| Customer app | Support | /support | none | slice-PR pending | 5 (phase-5 slice) |
| Customer app | City selection | /city-selection | none | slice-PR pending | 5 (phase-5 slice) |
| Customer app | Checkout success | /checkout/success | none | slice-PR pending | 5 (phase-5 slice) |
| Customer app | Retailers list | /retailers · retailer/search/ | none | slice-PR pending | 5 (phase-5 slice) |
| Customer app | Privacy policy page | /privacy-policy | none | slice-PR pending | 5 (phase-5 slice) |
| Platform | Seed idempotent; live-host guard | seed_e2e · fixtures.ts | seed.spec.ts › S1; guard.spec.ts › G1–G3 | covered | 5 (phase-5 slice) |
