# ADR-002: Defer customer JWT until email verification (preserve guest cart)

- **Status:** Accepted
- **Date:** 2026-05-24
- **Tickets:** [KAN-14](https://vin8003.atlassian.net/browse/KAN-14)
- **Work snapshot:** [../tickets/KAN-14.md](../tickets/KAN-14.md)
- **Flow:** [../07-KEY-FLOWS/guest-cart-signup.md](../07-KEY-FLOWS/guest-cart-signup.md)

## Context

Anonymous customers can add items to a guest cart, then start signup. Promoting JWTs immediately on register made the app treat the user as authenticated before email OTP. Guest cart lookup stopped; backend cart for the unverified account was empty. Back-button and abandoned-verification cases lost the cart.

## Decision

On register, store tokens in **temporary** localStorage keys. Keep `isGuest = true` until OTP succeeds. Then promote tokens, call `syncGuestCart()`, and enter the authenticated storefront.

Do **not** sync the guest cart onto an unverified account at signup time: if the user abandons OTP, stale unverified accounts can be deleted and the cart is gone.

## Consequences

- Guest cart remains visible if the user hits Back from `/verify-email`.
- Successful OTP merges guest items into the new account.
- Direct visit to `/verify-email` without temp tokens should verify then send the user to login.

## Snapshot source

Copied from Confluence technical proposal; Confluence retained. GitBook copy retained as presentation.
