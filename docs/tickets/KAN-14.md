---
id: KAN-14
title: Cart lost during signup (back button)
knowledge_class: durable
owning_repo: customer_ordereasy_njs
durable_docs:
  - docs/07-KEY-FLOWS/guest-cart-signup.md
  - docs/decisions/ADR-002-deferred-token-guest-cart.md
jira: https://vin8003.atlassian.net/browse/KAN-14
confluence: https://vin8003.atlassian.net/wiki/spaces/KAN/pages/98367/KAN-14+Cart+Lost+During+Signup+Back+Button+Bug+-+Technical+Proposal
gitbook: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/open-jira-ticket-docs/kan-14-cart-lost-during-signup
---

# KAN-14 Cart lost during signup

Work snapshot. Durable flow: [guest-cart-signup.md](../07-KEY-FLOWS/guest-cart-signup.md). Decision: [ADR-002](../decisions/ADR-002-deferred-token-guest-cart.md).

Historical PR: `customer_ordereasy_njs` #3, branch `fix/kan-14-cart-loss-signup`.

## Bug

Guest adds items, starts signup, hits Back from `/verify-email` (or never finishes OTP): cart is empty.

## Causes

1. **Premature token promotion** in `SignupPage`: JWTs stored as `customer_access_token` before email verify → `isGuest = false` → CartContext hits backend with unverified token → empty cart.
2. **No `syncGuestCart()`** on verify-email success (login flow does sync; signup did not).

## Solution (implemented in the proposal)

- Register → `temp_customer_access_token` / `temp_customer_refresh_token` only
- OTP success → `setAuthToken`, clear temp keys, `await syncGuestCart()`, go to storefront
- Verify without temp tokens → after OTP, send to login

Rejected: sync cart at signup onto an unverified account (abandonment + stale account delete destroys the cart).

## Tests from the proposal

1. Back button: guest cart remains
2. Full signup: cart merged after OTP
3. Direct `/verify-email`: OTP then login
