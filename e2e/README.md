# OrderEasy e2e (Playwright) — OE-367 / OE-368 / OE-369

Browser journeys across the retailer app, the customer app and this API, run against a
throwaway **local** stack only. Pass spec: QA's `CASES.md` (case ids are in every test title).

## Safety rails
- **Network guard** (`fixtures.ts`): every page and API request to `*.ordereasy.win` is aborted,
  recorded, and fails the test naming the URL (G1/G2). All other non-local hosts (Firebase, Google)
  are aborted too. No test ever reaches the internet.
- URLs come only from `env.ts` (defaults `127.0.0.1:8100/4273/4276`); G3 asserts they are local
  and that `.github/workflows/e2e.yml` contains no live host.
- `seed_e2e` refuses any database host that is not local / the CI service container.
- Backend runs with `ordering_platform.settings_e2e` (console logging, local file storage, no SMS);
  production settings are unchanged. Frontends are production static builds with
  `NEXT_PUBLIC_API_BASE_URL` pointing at the local API and dummy Firebase config; CI's "Bundle guard"
  fails if either build still contains a live host URL.
- Email uses Django's in-memory backend and SMS is off; auth specs read OTPs from the DB (`latestOtp`).
- Customer auth uses the seeded password login (`auth/customer/login/`, username `+91…`); never OTP.
- Browser: `timezoneId: 'Asia/Kolkata'`, locale `en-IN`. Trace + video retained on failure,
  screenshot on failure. CI uploads `playwright-report/` and `test-results/`.

## Run locally
```bash
# Postgres for the e2e DB, then from the RCP root:
export DJANGO_SETTINGS_MODULE=ordering_platform.settings_e2e DB_ENGINE=django.db.backends.postgresql \
       DB_NAME=oe_e2e DB_USER=postgres DB_PASSWORD=... DB_HOST=127.0.0.1 DB_PORT=5432
python manage.py migrate && python manage.py seed_e2e
python manage.py runserver 127.0.0.1:8100 --noreload &

# Each app checkout (dummy Firebase NEXT_PUBLIC_* values: copy from .github/workflows/e2e.yml):
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8100 npm run build && npx serve@14 out -l tcp://127.0.0.1:4273   # retailer
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8100 NEXT_PUBLIC_RETAILER_PORTAL_URL=http://127.0.0.1:4273 \
  npm run build && npx serve@14 out -l tcp://127.0.0.1:4276                                          # customer

cd e2e && npm ci && npx playwright install chromium
npx playwright test            # headless; every test reseeds (one worker)
npx playwright test --list     # every CASES.md id
E2E_RUN_FIXME=1 npx playwright test tests/fixme.spec.ts   # check whether F1–F9 bugs are still there
```
Override hosts with `E2E_API_URL`, `E2E_RETAILER_URL`, `E2E_CUSTOMER_URL`; the manage command with `E2E_MANAGE_CMD`.

## Cases → specs
| CASES.md | spec |
|---|---|
| A1–A6 POS bills | `tests/pos.spec.ts` |
| B1–B4 customer order lifecycle (+ filters/detail regression) | `tests/order.spec.ts` |
| C1–C5 khata payments | `tests/khata.spec.ts` |
| F1–F9 known bugs (`test.fixme` + `bug` annotation, assert correct values) | `tests/fixme.spec.ts` |
| G1–G3 network guard | `tests/guard.spec.ts` (G2 is `test.fail` by design) |
| T1–T2 IST midnight | `tests/time.spec.ts` |
| R-AUTH1–6 retailer signup, admin approval, login refusals, reset, profile | `tests/auth-retailer.spec.ts` |
| C-AUTH1–5 customer signup + email verify, login refusals, email reset, profile | `tests/auth-customer.spec.ts` |
| S1 seed idempotent / refuses remote DB | `tests/seed.spec.ts` + `retailers/tests/test_seed_e2e.py` |

Deviation: SL1 is "next day 10:00–12:00"; the API offers it as 30-minute slots, so journeys book 10:00–10:30.

Feature coverage and the phase plan: [COVERAGE.md](COVERAGE.md).

## Test ids
See [TESTIDS.md](TESTIDS.md). Ids are attributes only.

## CI: which FE code is tested
- **RCP pull_request:** for each FE repo, CI checks out the branch with the same name as the RCP PR head branch if one exists, otherwise `main`. For paired changes, use the same branch name in all three repos (for example `e2e/pr1-suite`). The "Pick FE refs" step logs the refs it picked.
- **FE-repo PRs** (via `workflow_call`): CI uses the FE PR head that was passed in, and `main` for the other FE repo.
- **Push to main:** CI uses both FE `main` branches.
- **Push to main / nightly failure:** the `alert` job opens (or comments on) one issue labelled `e2e-nightly-failure`.
