/**
 * Khata (udhaar): credit sale, payment received, ledger/statement, credit limits,
 * and the customer's own khata view. Seed: C1@R1 limit 5000 / balance 500; C1@R2 limit 0 / balance 1000.
 */
import { test, expect, urls } from '../fixtures';
import { authed, customerLogin, customerToken, getJson, khataBalance } from '../helpers';
import { fixme, known, posBill } from '../edge';
import { C1_MOBILE, SEED } from '../seed';

const C1 = { mobile: C1_MOBILE, name: SEED.customers.C1.first_name };

test.describe('Khata ledger', { tag: ['@khata'] }, () => {
  test('K1 credit sale adds a SALE row and raises the balance by the bill @retailer', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const bill = await posBill(api, rt, [[seed.products.P4, 2, 'P4']], { credit: 60 }, C1);
    expect(bill.status(), await bill.text()).toBe(201);
    expect(await khataBalance(api, rt, seed.customers.C1)).toBe(560);
    const ledger = await getJson(api, `customer/retailer/ledger/${seed.customers.C1}/`, rt);
    expect(ledger.count).toBe(1);
    expect(ledger.results[0]).toMatchObject({ transaction_type: 'SALE', amount: '60.00', balance_after: '560.00' });
    expect(ledger.results[0].notes).toMatch(/^POS Udhaar for Order #ORD-/);
  });

  test('K2 payment received lowers the balance and the statement runs newest first @retailer', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    expect((await posBill(api, rt, [[seed.products.P4, 2, 'P4']], { credit: 60 }, C1)).status()).toBe(201);
    for (const [amount, mode] of [[100, 'cash'], [50, 'upi']] as const) {
      const r = await api.post('customer/retailer/payment/record/', {
        ...authed(rt), data: { customer_id: seed.customers.C1, amount, payment_mode: mode, notes: `E2E ${mode}` },
      });
      expect(r.status(), await r.text()).toBe(201);
    }
    expect(await khataBalance(api, rt, seed.customers.C1)).toBe(410);
    const rows = (await getJson(api, `customer/retailer/ledger/${seed.customers.C1}/`, rt)).results;
    expect(rows.map((r: { transaction_type: string; amount: string; balance_after: string; payment_mode: string | null }) =>
      [r.transaction_type, r.amount, r.balance_after, r.payment_mode])).toEqual([
      ['PAYMENT', '50.00', '410.00', 'upi'],
      ['PAYMENT', '100.00', '460.00', 'cash'],
      ['SALE', '60.00', '560.00', null],
    ]);
  });

  test('K3 credit limit: a sale up to the available amount passes, one rupee more is refused @retailer', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    // Available 4500. 18×P1 = 4500 fits exactly; then 1×P4 (30) exceeds.
    expect((await posBill(api, rt, [[seed.products.P1, 18, 'P1']], { credit: 4500 }, C1)).status()).toBe(201);
    expect(await khataBalance(api, rt, seed.customers.C1)).toBe(5000);
    const over = await posBill(api, rt, [[seed.products.P4, 1, 'P4']], { credit: 30 }, C1);
    expect(over.status()).toBe(400);
    expect(await over.text()).toContain('Credit limit exceeded. Limit: ₹5000.00');
    expect(await khataBalance(api, rt, seed.customers.C1)).toBe(5000);
  });

  test('K4 lowering the limit blocks the next credit sale; the customer sees the new limit @retailer @customer', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const upd = await api.patch(`customer/retailer/credit-limit/update/${seed.customers.C1}/`, { ...authed(rt), data: { credit_limit: 520 } });
    expect(upd.status(), await upd.text()).toBe(200);
    const over = await posBill(api, rt, [[seed.products.P4, 1, 'P4']], { credit: 30 }, C1);
    expect(over.status()).toBe(400);
    expect(await over.text()).toContain('Limit: ₹520.00');
    const ct = await customerToken(api, C1_MOBILE);
    const r1 = (await getJson(api, 'customer/credit/all/', ct)).find((k: { retailer_id: number }) => k.retailer_id === seed.retailers.R1);
    expect(r1).toMatchObject({ credit_limit: 520, current_balance: 500, remaining_credit: 20 });
  });

  test('K5 the customer profile shows outstanding, limit and remaining credit per shop @customer', async ({ page, api, seed, retailerToken }) => {
    const rt = await retailerToken();
    expect((await posBill(api, rt, [[seed.products.P4, 2, 'P4']], { credit: 60 }, C1)).status()).toBe(201);
    await customerLogin(page, C1_MOBILE);
    await page.goto(`${urls.customer}/profile`);
    await expect(page.getByText('Credit / Khata')).toBeVisible();
    const kirana = page.locator('div', { hasText: SEED.retailers.R1.shop_name }).filter({ hasText: 'Remaining credit' }).last();
    await expect(kirana).toContainText('Outstanding₹560.00');
    await expect(kirana).toContainText('Credit limit₹5000.00');
    await expect(kirana).toContainText('Remaining credit₹4440.00');
  });

  fixme('K6 a shop with no credit limit (0 = unlimited) never shows negative remaining credit @customer',
    known('NEW', 'customer/credit/all and the profile show "Remaining credit ₹-1000.00" for a limit-0 (no lock) khata'),
    async ({ api, seed }) => {
      const ct = await customerToken(api, C1_MOBILE);
      const r2 = (await getJson(api, 'customer/credit/all/', ct)).find((k: { retailer_id: number }) => k.retailer_id === seed.retailers.R2);
      expect(r2.current_balance).toBe(1000);
      expect(r2.remaining_credit).toBeGreaterThanOrEqual(0);
    });

  fixme('K7 staff without khata permission get 403 (not 500) when recording a payment @retailer',
    known('NEW', 'staff POST customer/retailer/payment/record/ returns 500 "No RetailerProfile matches"'),
    async ({ api, seed, retailerToken }) => {
      const rt = await retailerToken();
      const org = (await getJson(api, 'retailers/profile/', rt)).organization_id;
      const role = await (await api.post(`retailers/org/${org}/roles/`, { ...authed(rt), data: { name: 'E2E Khata Reader', slug: 'e2e-khata-reader', permissions: ['orders.read'] } })).json();
      expect((await api.post(`retailers/org/${org}/staff/`, { ...authed(rt), data: { role_id: role.id, username: 'e2es_khata', password: 'E2e-Pass-123!' } })).status()).toBe(201);
      const login = await (await api.post('auth/retailer/login/', { data: { username: 'e2es_khata', password: 'E2e-Pass-123!' } })).json();
      const st = login.tokens?.access ?? login.access;
      const r = await api.post('customer/retailer/payment/record/', { ...authed(st), data: { customer_id: seed.customers.C1, amount: 10, payment_mode: 'cash' } });
      expect(r.status()).toBe(403);
    });
});
