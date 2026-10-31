# Retailer verification: design proposal

- **Status:** proposal for Vineet's review. No code changes in this PR.
- **Scope:** backend (`RetailerCustomerPlatform`), retailer app (`retailer_ordereasy_njs`), customer app (read side only).

## 1. What exists today

Read from `main` on 2026-10-31.

**Signup.** `POST auth/retailer/signup/` (`authentication/views.py: retailer_signup`) creates the user and a `RetailerProfile` with placeholder data: shop name "<name>'s Shop", empty address, pincode `000000`, `verification_status='pending'`, `is_verified=False`, `is_active=False`. The signup form asks only for username, email, phone and password. Phone OTP exists (`User.is_phone_verified`, `OTPVerification`, an SMS provider via Authkey) and the profile page has a "Verify Now" button, but nothing requires it for approval.

**Approval.** One flag pair: `verification_status` (`pending|approved|rejected`) plus `is_verified`. Platform admins (`is_staff`, superuser, or an email in `ADMIN_EMAILS`) call `GET admin/verifications/` and `POST admin/verifications/<id>/action/` with `approve` or `reject` and a free-text reason. Approve sets `is_active=True` (first time only). Reject sets `is_active=False` and stores `rejection_reason`. There is no history of who decided what or when, and no checklist.

**What gates customers.** `RetailerProfile.objects.public()` requires `is_active`, `is_verified` and `approved`. Every customer-facing shop, catalog, cart and order lookup goes through it, so an unapproved shop and all its products are invisible to customers. This is a good single choke point to build on.

**Data captured but never checked.** `gst_number` and `pan_number` are format-checked by regex only (no checksum, no registry lookup, no uniqueness across shops). `upi_id` is free text. Address and lat/lng are optional. `shop_image` is any image. Nothing is stored for identity or business documents.

**Products.** `Product` (per retailer) has `name`, `description`, `category`, `brand`, images, `is_active`, `is_available`. A retailer can create products freely. They are visible to customers as soon as the shop is public. There is no review, report or takedown model for products or shops. Only `ProductReview` and `RetailerReview` (ratings) exist. `MasterProduct` is a curated catalog keyed by barcode that products can link to.

**Admin UI.** Retailer app page `dashboard/admin/verifications` (visible when `is_admin`): tabs per status, search, a card per retailer with contact, address, GST/PAN, an Approve button and a Reject dialog with reason. Retailers see `VerificationAlertBanner` (Hindi and English) saying pending or rejected with the reason.

**Gaps that matter.**
1. Approval is a single judgment call with nothing to base it on: address is empty and phone may be unverified.
2. After approval, the retailer can still edit shop name, image, address and GST without re-review. Confirm with a test before relying on this, I did not run it.
3. Product content is unmoderated and there is no way for a customer to report anything.
4. The only enforcement lever is reject, which also hides everything, with no "suspended" state and no audit trail.

## 2. Principles

- Verify cheap things automatically, spend admin time only on judgment calls.
- Let a retailer start working immediately (add products, use the POS) but control what customers can see.
- Our shops are mostly Hindi-first, small kirana and mithai stores, many without GST. Do not make GST mandatory.
- Everything an admin does is logged.

## 3. Store approval

### 3.1 Statuses

Replace `pending|approved|rejected` with a single `verification_status`, keeping `is_verified` as a derived field so existing code and `public()` keep working.

| Status | Meaning | Customers see shop? | Can sell via POS? |
|---|---|---|---|
| `draft` | Signed up, profile incomplete | No | Yes |
| `submitted` | All required checks passed, waiting for admin | No | Yes |
| `needs_changes` | Admin asked for a fix (reason shown) | No | Yes |
| `approved` | Admin approved | Yes | Yes |
| `limited` | Approved with limits (see 3.4); the default after first approval | Yes, with limits | Yes |
| `suspended` | Taken down by admin (reason, appealable) | No | Read-only |
| `rejected` | Final no (fraud, fake shop) | No | No |

The POS and the retailer dashboard must keep working in every state except `rejected`, because the retailer's own billing is not a customer-safety risk.

### 3.2 Checks

| Check | Automated? | Rule | Blocking for submit? |
|---|---|---|---|
| Phone | Yes | OTP verified on the signup number (`is_phone_verified`) | Yes |
| Email | Yes | Existing email OTP | No, nice to have |
| Shop name | Yes | Not a placeholder, 3 to 60 chars, passes the text screen in 4.3, no duplicate name in the same pincode | Yes |
| Address | Partly | Address line, city, state, 6-digit pincode that exists, and a map pin (lat/lng) set by the retailer on the map. Auto flag if pin is more than 3 km from the pincode centre | Yes |
| Shop photo | Partly | At least one storefront photo. Auto: image size, not blurry, not a stock/duplicate hash match. Admin eyeballs it | Yes |
| Owner identity | Manual (v1) | Photo of an ID (Aadhaar masked, PAN, voter ID or driving licence), plus optional selfie holding the shop board. Stored privately, viewable by admins only | Required for full approval, not for submit |
| Business registration | Partly | One of: GSTIN, FSSAI (food shops), Shop and Establishment/Udyam number, or a trade licence photo. If GSTIN: validate format + checksum and cross-check name and state with the GST portal API when we have one; until then admin checks manually | One of these or a shop-board photo |
| UPI / bank | Partly | UPI ID must match `name@psp` format. Optional penny-drop (Rs 1) verification later. Name on UPI should match owner or shop | No (only needed before online payments are enabled) |
| Duplicates | Yes | Same phone, GSTIN, PAN, UPI ID or ID number on another shop raises a flag for the admin | Flag, not block |
| Fraud signals | Yes | Disposable email domain, many signups from one device/IP, banned phone | Flag |

Auto results are stored per check as `pass | flag | fail | manual`, so the admin sees only what needs a human.

### 3.3 What can be automated

- Auto-pass: phone OTP, address completeness, pincode validity, GST/PAN format, duplicate scan, text screen.
- Auto-route: a shop where every check is `pass` and there is no duplicate flag goes to a fast lane ("quick approve", one tap). A shop with any `flag` goes to a normal queue with the reasons on top.
- Do not auto-approve in v1. The cost of one fake shop reaching customers outweighs the saved admin minute. Revisit after we have 100 decisions to measure false positives.

### 3.4 Limited status (recommendation: yes, use it)

After first approval a shop is `limited` for its first 30 days or first 25 orders, whichever comes later:

- Visible to customers, labelled nothing special.
- COD only, no online payment until UPI/bank is verified.
- Max 200 live products, max order value Rs 5,000, 20 orders/day.
- Product edits to name, image and category go through the post-publish review queue (section 4).
- Auto-promoted to `approved` with no admin action once the window passes with no open reports. Admin can promote earlier or demote.

This gives a new shop real traffic while capping damage.

### 3.5 Re-verification triggers

Moving back to `needs_changes` (shop hidden until fixed) when the retailer changes: shop name, address or pin, GSTIN/PAN, owner phone. Changing the logo, description, hours, delivery settings does not trigger it. Only shops that are already live get a grace flow: the change is held as pending and the old values stay live until approved.

## 4. Product handling

### 4.1 Options

| | A. Approve before live | B. Live immediately, review after | C. Tiered (recommended) |
|---|---|---|---|
| Customer safety | Best | Weakest | Good |
| Retailer experience | Slow, painful for 500-item catalogs | Instant | Instant for safe items |
| Admin load | Every product, does not scale | Only reported/flagged | Only flagged and new-shop items |
| Fit for kirana bulk uploads | Poor | Good | Good |

### 4.2 Recommendation: C, tiered

1. **Master catalog items are live immediately.** A product linked to a `MasterProduct` (barcode match) inherits the curated name, image and category. Retailers only set price and stock. This should be the main path, it removes most abuse by construction and also fixes duplicate and messy catalog data.
2. **Custom products from an `approved` shop go live immediately** but pass automated checks first (4.3). Anything that fails the checks is held as `pending_review`, invisible to customers, and the retailer sees why.
3. **Custom products from a `limited` shop**: name, image and category pass through automated checks, and the first 20 products are sampled by an admin after going live (post-publish review). Anything the admin rejects is hidden and the shop gets a strike.
4. **Restricted categories** (alcohol, tobacco, medicines, adult, weapons, pesticides) always need admin approval before they go live, and in v1 the recommendation is to block alcohol, adult and weapons outright.

Add `Product.moderation_status` with `ok | pending_review | hidden | removed`, `moderation_reason`, `moderated_by`, `moderated_at`. Customer queries add `moderation_status='ok'` next to the existing out-of-stock filter (`hide_oos_for_customer` is the natural place), so the filter lives in one spot.

### 4.3 Automated checks

| Field | Check |
|---|---|
| Name and description | Blocklist (Hindi, Hinglish, English profanity and restricted items), phone numbers/URLs/WhatsApp links in the name, all-caps or symbol spam, length limits, repeated characters |
| Image | Format and size limits (exists), NSFW/violence classifier (a hosted moderation API; roughly Rs 0.1 to 0.2 per image), perceptual hash against a banned-image list, text-in-image phone number detection (later) |
| Category | Name keywords vs chosen category (e.g. "whiskey" in Grocery), restricted-category list |
| Price | Warn if price is 0, far above MRP of the linked master product, or changes by more than 10x |
| Volume | Rate-limit new products per hour per shop to stop scripted floods |

Failures are `pending_review` (soft) or `hidden` (hard, such as a banned hash). Classifier cost applies only to custom uploads, not master-catalog items.

### 4.4 Admin controls on products

Hide, remove, require edit with a reason, bulk hide all products of a shop, and ban an image hash across all shops.

## 5. Customer protection

- **Report button** on shop and on product pages in the customer app: reasons (fake or misleading, offensive, illegal or restricted item, wrong price, never delivered, other), optional text and photo. Logged-in customers only, rate-limited, one open report per customer per target.
- **Report model**: `Report(target_type shop|product, target_id, reporter, reason, text, status open|actioned|dismissed, handled_by, handled_at)`.
- **Auto-hide threshold**: a product with 3 reports from different customers is auto-hidden (`pending_review`) until an admin looks, a shop with 5 reports from different customers in 7 days is auto-set to `limited` and flagged. This is protection against abuse of the report button too, so repeated bogus reporters are down-weighted.
- **Admin actions**: dismiss, hide product, remove product, warn shop (message in app), strike, suspend shop, reject shop. Three strikes in 90 days suspends the shop automatically.
- **Suspension**: shop disappears from customer lists and search immediately (via `public()`), open orders can still be completed or cancelled with refund, retailer sees reason and an appeal button that creates a review task.
- **Audit**: every status change writes `VerificationEvent(shop, actor, from, to, reason, created_at)`. Admins never edit status without a reason.
- **Retailer-visible notices**: push/WhatsApp and in-app message for every hide, strike and suspension, with the policy line broken and how to fix it.

## 6. UI/UX

### 6.1 Retailer onboarding (mobile-first, Hindi + English)

A 5-step checklist replaces the banner as the first screen after signup. It shows progress ("3 of 5 done") and what is left.

1. **Phone**: OTP inline.
2. **Shop**: name, type, storefront photo.
3. **Address**: address fields plus a map pin to drag. Check shown: pin matches pincode.
4. **Business proof**: pick one of GST, FSSAI, shop licence or board photo, then upload.
5. **Owner ID**: ID photo (+ optional selfie). Text: "Only our team sees this. We never share it."

Each step shows a status chip: Done, Needs fix (with reason), Checking. UPI is a separate optional "Start online payments" card after approval.

### 6.2 Status the retailer sees

A persistent status card on the dashboard top: Draft ("Finish 2 steps to go live"), Submitted ("We are checking, usually within 24 hours"), Needs changes (reason plus a Fix button that opens the exact step), Live (Limited: "You can sell up to Rs 5,000 per order until <date>"), Suspended (reason plus Appeal). Products list shows a badge per product: Live, Under review (with reason), Hidden.

### 6.3 Admin review screens

- **Queue** (extends the current verifications page): tabs Submitted, Flagged, Needs changes, Limited, Suspended, with counts and sort by oldest first. Reports tab and Products tab next to it.
- **Shop review page**: left, the retailer's data and photos; right, a **checks panel** with each check as a row (Pass, Flag, Manual) and a one-line reason, for example "Phone OTP verified: pass", "GSTIN valid format; name match: manual", "Same UPI on shop #214: flag". Duplicates link to the other shop. Below: product sample (first 20 products with images and automated results) and report history.
- **Actions**: Approve (limited by default), Approve fully, Ask for changes (pick a step plus message), Reject, Suspend. A reason is required except for plain approve. History timeline at the bottom.
- **Product review**: grid of images, name, category, shop and the check that fired; one-click Approve, Hide, Remove, "Ban image".
- **Report inbox**: report text, target preview, reporter history, one-click actions.

## 7. Rollout plan

1. **Foundation (small)**: statuses, `VerificationEvent` audit log, per-check results, derive `is_verified` and keep `public()` unchanged, existing approved shops migrate to `approved`.
2. **Onboarding checklist + admin checks panel** in the retailer app.
3. **Reports and suspension**, then **product moderation status** with the customer filter.
4. **Automated product checks** (blocklist first, image classifier second).
5. **Limited status rules** and auto-promotion.

Existing live shops stay live; run the new checks over them in the background and only flag, never hide, on the first pass.

## 8. Decisions needed from Vineet

| # | Question | Recommendation |
|---|---|---|
| 1 | Is GST required? | No. One of GST, FSSAI, shop licence or shop-board photo. |
| 2 | Collect owner ID photo? | Yes, privately stored, admin-only; required for full approval. Tell me if you want to avoid holding ID images and rely on phone + shop photo + GST instead. |
| 3 | Approve as `limited` first? | Yes, 30 days or 25 orders. |
| 4 | Product approval model | Tiered (section 4.2). |
| 5 | Which categories are banned vs admin-approved? | Ban alcohol, adult, weapons; admin-approve tobacco, medicines, pesticides. |
| 6 | Auto-approve for clean shops? | Not in v1, revisit after 100 decisions. |
| 7 | Image moderation vendor and budget | Hosted moderation API; confirm a monthly cap. |
| 8 | Who reviews? | Just you for now, with a second admin role later (the code already has `ADMIN_EMAILS`). |
| 9 | Existing live shops | Keep live, flag silently, no forced re-verification. |
| 10 | Strike policy | 3 strikes in 90 days suspends. |
