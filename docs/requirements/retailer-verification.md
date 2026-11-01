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

Decided: one-time approval, no limited phase. Keep `verification_status` and `is_verified` working as today and add only what is needed.

| Status | Meaning | Customers see shop? | Can sell via POS? |
|---|---|---|---|
| `pending` | Signed up or submitted, waiting for admin (as today) | No | Yes |
| `needs_changes` | Admin asked for a fix (reason shown) | No | Yes |
| `approved` | Admin approved once; full access | Yes | Yes |
| `suspended` | Taken down by admin (reason, appealable) | No | Read-only |
| `rejected` | Final no (fraud, fake shop) | No | No |

The retailer can use the POS and dashboard in every state except `rejected`. `public()` keeps working unchanged: suspended and needs_changes are simply not `approved`.

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

- Auto-pass: phone OTP, address completeness, pincode validity, GST/PAN format, duplicate scan, text screen. All are cheap string/DB checks that run in the signup request.
- The admin sees a checks panel and a **Quick approve** button when everything is pass. Budget: 10 shops/week at ~30 min today is 5 hours/week. With the panel the target is under 10 minutes for a clean shop.
- No auto-approval in v1.

### 3.4 Re-verification triggers

Moving back to `needs_changes` (shop hidden until fixed) when the retailer changes: shop name, address or pin, GSTIN/PAN, owner phone. Changing the logo, description, hours, delivery settings does not trigger it. To keep admin work small, only shop name, address/pin and GSTIN/PAN changes re-trigger it, and an approved shop keeps its old values live until the admin approves the change.

## 4. Product handling

### 4.1 Options

| | A. Approve before live | B. Live immediately, review after | C. Tiered (recommended) |
|---|---|---|---|
| Customer safety | Best | Weakest | Good |
| Retailer experience | Slow, painful for 500-item catalogs | Instant | Instant for safe items |
| Admin load | Every product, does not scale | Only reported/flagged | Only flagged and new-shop items |
| Fit for kirana bulk uploads | Poor | Good | Good |

### 4.2 Recommendation: tiered, no per-product approval queue

Decided direction: no extra friction or load, only quick automated checks and one-time approval.

1. **Master catalog items are live immediately** (inherit curated name, image, category).
2. **Custom products from an approved shop go live immediately** after the cheap automated text checks in 4.3. A product that fails is held as `pending_review` and the retailer sees why. There is no routine admin review of products.
3. **Banned categories** (decided): alcohol, tobacco, adult, weapons are rejected by the text checks. **Restricted** (medicines, pesticides) are held for admin approval; expect few.
4. Safety net after publish is customer reports (section 5), not a queue.

Add `Product.moderation_status` with `ok | pending_review | hidden | removed`, `moderation_reason`, `moderated_at`. Customer queries add `moderation_status='ok'` beside the existing out-of-stock filter (`hide_oos_for_customer`).

### 4.3 Automated checks (sized for one small VM and one database)

All checks run in-process on product create/update, are pure string or single-row checks and add no new service.

| Field | Check |
|---|---|
| Name and description | Keyword blocklist (English, Hindi, Hinglish) for banned categories and abuse, phone numbers/URLs in the name, length limits, symbol/caps spam |
| Category | Banned/restricted keywords vs chosen category |
| Image | Existing size limit and resize only. **No image classifier in v1**: it costs money and CPU/latency. Images are covered by reports and the admin "hide / ban image" action. Revisit when volume or abuse justifies an external moderation API |
| Price | Warn if price is 0 or wildly above the master MRP |
| Volume | Rate-limit product writes per shop (e.g. 60/min) to stop scripted floods |

Keep the blocklist in a small DB table or settings file the admin can edit without a deploy. Do not scan the existing catalog in the web process; if a backfill is wanted, run it as a one-off management command at night in small batches.

### 4.4 Admin controls on products

Hide, remove, require edit with a reason, bulk hide all products of a shop, and ban an image hash across all shops.

## 5. Customer protection

- **Report button** on shop and on product pages in the customer app: reasons (fake or misleading, offensive, illegal or restricted item, wrong price, never delivered, other), optional text and photo. Logged-in customers only, rate-limited, one open report per customer per target.
- **Report model**: `Report(target_type shop|product, target_id, reporter, reason, text, status open|actioned|dismissed, handled_by, handled_at)`.
- **Auto-hide threshold**: a product with 3 reports from different customers is auto-hidden (`pending_review`) until an admin looks, a shop with 5 reports from different customers in 7 days is flagged to the admin report inbox for review. This is protection against abuse of the report button too, so repeated bogus reporters are down-weighted.
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

A persistent status card on the dashboard top: Pending ("Finish 2 steps to go live" while steps are missing, then "We are checking, usually within 24 hours"), Needs changes (reason plus a Fix button that opens the exact step), Live, Suspended (reason plus Appeal). Products list shows a badge per product: Live, Under review (with reason), Hidden.

### 6.3 Admin review screens

- **Queue** (extends the current verifications page): tabs Pending, Flagged, Needs changes, Suspended, with counts and sort by oldest first. Reports tab and Products tab next to it.
- **Shop review page**: left, the retailer's data and photos; right, a **checks panel** with each check as a row (Pass, Flag, Manual) and a one-line reason, for example "Phone OTP verified: pass", "GSTIN valid format; name match: manual", "Same UPI on shop #214: flag". Duplicates link to the other shop. Below: product sample (first 20 products with images and automated results) and report history.
- **Actions**: Approve (quick approve when all checks pass), Ask for changes (pick a step plus message), Reject, Suspend. A reason is required except for plain approve. History timeline at the bottom.
- **Product review**: grid of images, name, category, shop and the check that fired; one-click Approve, Hide, Remove, "Ban image".
- **Report inbox**: report text, target preview, reporter history, one-click actions.

## 7. Rollout plan

1. **Foundation**: new statuses (`needs_changes`, `suspended`), `VerificationEvent` audit table, per-check results on the profile. Existing approved shops stay `approved`.
2. **Onboarding checklist + admin checks panel with Quick approve** in the retailer app.
3. **Reports, strikes and suspension**, then `Product.moderation_status` and the customer filter.
4. **Text checks** for products.
5. Image moderation only if needed later.

Infra notes: Oracle free tier, one VM, one DB. Add indexes only on columns used by the queues (`verification_status`, `moderation_status`, report `status`); paginate admin lists as the current verifications API already does; keep ID and shop photos in the existing media storage with admin-only access; avoid background workers (do checks inline, they are cheap). Existing live shops stay live; no mass re-scan.

## 8. Decisions

Decided by Vineet on 2026-10-31:

| # | Question | Decision |
|---|---|---|
| 1 | GST required? | No. One of GST, FSSAI, shop licence or shop-board photo. |
| 2 | Owner ID photo? | Yes, stored privately, admin-only. |
| 3 | Limited-first approval? | No. One-time full approval. |
| 4 | Product model | No extra friction: quick automated checks only, no per-product approval queue. |
| 5 | Banned categories | Alcohol, tobacco, adult, weapons. Medicines and pesticides need admin approval. |
| 6 | Auto-approve clean shops | Not in v1. |
| 7 | Review capacity | About 10 shops a week at 30 min each; the checks panel and Quick approve should cut that. |
| 8 | Infra | Thin: one Oracle free-tier VM and one DB, so no image classifier or workers in v1. |

Still open (small, defaults in the doc apply unless changed):

- Image moderation later: external API vs none. Default none.
- Strike policy: 3 strikes in 90 days suspends. Default as written.
- Report auto-hide: 3 distinct reporters hides a product. Default as written.
- Second admin: later.

## 9. Implementation status

### Step 1: backend foundation (shipped in `claude/verification-foundation`)

- **Statuses:** `pending`, `needs_changes`, `approved`, `suspended`, `rejected`. `is_verified` is true only for `approved`, and `public()` is unchanged, so every status except approved is hidden from customers.
- **Automated checks** (`retailers/verification.py`, text rules in `common/content_rules.py`): phone OTP, shop name (placeholder, length, banned or abusive words, phone numbers or links), storefront photo present, address plus valid pincode plus map pin, business proof (GSTIN format and checksum, PAN inside the GSTIN, or FSSAI/licence number plus photo, or a board photo), owner ID uploaded, and duplicate GSTIN/PAN/UPI/phone across shops. Each result is `pass`, `fail`, `flag` or `manual`. Only `fail` blocks submission.
- **Private documents:** `RetailerVerificationDocument` (proof, owner_id, selfie) is stored outside the public media bucket: `PRIVATE_MEDIA_ROOT` on disk (default `../ordereasy-private` next to the checkout), or a private S3 bucket when `PRIVATE_DOCS_BUCKET` is set. Files are checked by their bytes (JPG, PNG, WEBP, PDF, 5 MB max), and only the latest file of each kind is kept. Admins read them through an authenticated endpoint with `Cache-Control: no-store`. These files are not in the daily database backup.
- **Audit log:** `VerificationEvent` records every submit, admin action and post-approval profile change, with who, when, why and details.
- **Changes after approval:** editing shop name, address, city, state, pincode, GSTIN or PAN on an approved shop keeps it live, sets `verification_review_needed`, and logs the old and new values. The admin clears it with `mark_reviewed`.

Endpoints (all under `/api/retailer/`):

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `verification/` | Shop owner | Status, reason, five steps with done/needs fix, every check result, uploaded documents |
| POST | `verification/submit/` | Shop owner | Re-runs checks; 400 with the failing steps, or moves to `pending` with a submitted time |
| POST | `verification/documents/` | Shop owner | Multipart `kind` + `file`; 30 uploads/hour |
| PATCH | `profile/update/` | Shop owner | Existing; now also takes `proof_type`, `proof_number` |
| GET | `admin/verifications/?status=` | Admin | Adds `needs_changes`, `suspended`, `review_needed`; pending lists submitted shops first; rows carry the stored check counts |
| GET | `admin/verifications/<id>/` | Admin | Review page: profile, fresh checks, documents, audit log |
| GET | `admin/verifications/<id>/documents/<doc_id>/` | Admin | Streams a private document |
| POST | `admin/verifications/<id>/action/` | Admin | `approve`, `request_changes` (reason), `reject`, `suspend` (reason), `reinstate`, `mark_reviewed` |
