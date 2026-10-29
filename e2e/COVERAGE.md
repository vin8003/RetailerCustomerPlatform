# Feature coverage — Playwright e2e

One row per feature. *Covered* = at least one spec asserts the outcome (a `test.fixme` counts: the case exists and waits on a product fix).
Update the row in the PR that adds or removes a spec. Phases: 2 auth & account · 3 POS camera, delivery fee, bundles · 4 catalog, offers, inventory · 5 everything else.

## Totals

| phase | scope | covered / total |
|---|---|---|
| 2 | auth & account | 10 / 14 |
| 3 | POS camera scan, distance delivery fee, bundles | 2 / 5 |
| 4 | catalog, offers/coupons, inventory | 3 / 8 |
| 5 | orders edge cases, khata, reports, settings, rest | 5 / 16 |
| **all** | | **20 / 43** |

## Features

| area | feature | routes / endpoints (`/api/` omitted) | current coverage | target phase |
|---|---|---|---|---|
| Auth (retailer) | Retailer signup → pending approval banner | /signup · auth/retailer/signup/ | auth-retailer.spec.ts › R-AUTH1 | 2 |
| Auth (retailer) | Admin approves a pending retailer | /dashboard/admin/verifications · retailer/admin/verifications/, …/<id>/action/ | auth-retailer.spec.ts › R-AUTH2 | 2 |
| Auth (retailer) | Retailer login (success + wrong password + customer creds refused) | /login · auth/retailer/login/ | auth-retailer.spec.ts › R-AUTH3, R-AUTH4 (success: every retailer journey) | 2 |
| Auth (retailer) | Retailer password reset via phone OTP | /forgot-password · auth/retailer/password/forgot/, …/reset/ | auth-retailer.spec.ts › R-AUTH5 (test.fixme: product bug) | 2 |
| Account (retailer) | Shop profile edit persisted | /dashboard/profile · retailer/profile/, retailer/profile/update/ | auth-retailer.spec.ts › R-AUTH6 | 2 |
| Account (retailer) | Admin rejects a retailer (reason shown) | retailer/admin/verifications/<id>/action/ | none | 2 |
| Auth (customer) | Customer signup + email OTP verify | /signup, /verify-email · auth/customer/signup/, auth/verify-email/ | auth-customer.spec.ts › C-AUTH1 | 2 |
| Auth (customer) | Unverified email cannot log in | /login · auth/customer/login/ | auth-customer.spec.ts › C-AUTH2 | 2 |
| Auth (customer) | Customer login (success + wrong password) | /login · auth/customer/login/ | auth-customer.spec.ts › C-AUTH3 (success: every customer journey) | 2 |
| Auth (customer) | Email password reset | /forgot-password · auth/password/email/forgot/, …/reset/ | auth-customer.spec.ts › C-AUTH4 | 2 |
| Account (customer) | Profile edit persisted and shown | /profile · customer/profile/, customer/profile/update/ | auth-customer.spec.ts › C-AUTH5 | 2 |
| Auth | Resend email OTP / phone OTP verify | auth/resend-email-otp/, auth/customer/verify-otp/, …/resend-otp/ | none | 2 |
| Auth | Change password, logout, token refresh | auth/change-password/, auth/logout/, auth/token/refresh/ | none | 2 |
| Auth | Google login (customer) | auth/customer/google-login/ | none (needs Firebase stub) | 2 |
| POS | POS bills: UPI, khata, split, cash, unknown barcode | /dashboard/pos · products/erp/pos-checkout/ | pos.spec.ts › A1–A6 | 3 |
| POS | POS customer lookup / verify | products/erp/verify-pos-customer/, …/search-pos-customers/ | pos.spec.ts › A2, A3, A5 (partial) | 3 |
| POS | Mobile POS camera barcode scan (fake camera) | /dashboard/pos (mobile) | none | 3 |
| Delivery | Distance-based delivery fee at checkout | retailer/geo-estimate/ · cart/summary/ | none | 3 |
| Catalog | Bundles / product groups in cart and POS | products/product-groups/ | none | 3 |
| Catalog | Product create / edit / delete | products/create/, <id>/update/, <id>/delete/ | none | 4 |
| Catalog | Bulk upload sessions and images | products/upload/…, upload/session/… | none | 4 |
| Catalog | Categories and brands | products/categories/…, products/brands/… | none | 4 |
| Catalog | Customer storefront sections and search | products/retailer/<id>/…, retailer/search/ | order.spec.ts › B1 (browse + add only) | 4 |
| Offers | Percentage cap, stackable and non-stackable offers | offers · cart/ | fixme.spec.ts › F2, F3, F4 (test.fixme) | 4 |
| Offers | Offer + coupon discount shown once | cart/apply-coupon/ | fixme.spec.ts › F8 (test.fixme) | 4 |
| Offers | Coupon apply/remove, available coupons | cart/apply-coupon/, remove-coupon/, offers/available-coupons/<id>/ | none | 4 |
| Inventory | Stock write-off and inventory ledger | products/<id>/write-off/, erp/inventory-ledger/ | none | 4 |
| Orders | Order lifecycle pending → delivered (both apps) | orders/place/, <id>/status/ | order.spec.ts › B1–B4 | 5 |
| Orders | IST midnight dates and next-day slots | orders/ · slot picker | time.spec.ts › T1, T2; fixme.spec.ts › F6 | 5 |
| Orders | Packed straight from Confirmed | orders/<id>/status/ | fixme.spec.ts › F9 (test.fixme) | 5 |
| Orders | Cancel, modify/confirm modification | orders/<id>/cancel/, modify/, confirm_modification/ | none | 5 |
| Orders | Online payment submit/verify | orders/<id>/submit_payment/, verify_payment/ | none | 5 |
| Orders | Order chat, notes, feedback, ratings | orders/<id>/chat/…, notes/, feedback/, rate-customer/ | none | 5 |
| Returns | Return request | orders/<id>/return/, returns/ | none | 5 |
| Khata | Record khata payment, limits, R1/R2 isolation | customer/retailer/payment/record/, ledger/<id>/ | khata.spec.ts › C1–C5 | 5 |
| Khata | Credit limit update, blacklist toggle | customer/retailer/credit-limit/update/<id>/, blacklist/toggle/ | none | 5 |
| Loyalty | Loyalty points and redeem OTP | customer/loyalty/…, retailer/loyalty/redeem/ | none | 5 |
| Customer | Addresses and wishlist | customer/addresses/…, wishlist/… | none | 5 |
| Customer | Notifications, referrals | customer/notifications/…, referral/… | none | 5 |
| Reports | Dashboard summary, daily sales, stats, demand insights | products/erp/dashboard/summary/, daily-sales-summary/, stats/ | none | 5 |
| Settings | Operating hours, reward config, org settings | retailer/operating-hours/, reward-config/, org/ | none | 5 |
| Partner API | Partner API v1 keys and endpoints | api/v1/partner/ | none | 5 |
| Platform | Seed idempotent; live-host guard | seed_e2e · fixtures.ts | seed.spec.ts › S1; guard.spec.ts › G1–G3 | 5 |
