import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { getJson, khataBalance, retailerLogin, rupees } from '../helpers';
import { R2 } from '../seed';

async function openKhata(page: Page, customerId: number) {
  await page.goto(`${urls.retailer}/dashboard/customers/details?id=${customerId}`);
  await expect(page.getByTestId('customer-current-balance')).toBeVisible();
}

async function balanceOnScreen(page: Page) {
  return rupees(await page.getByTestId('customer-current-balance').textContent());
}

async function recordPayment(page: Page, amount: string) {
  await page.getByTestId('record-payment-open').click();
  await page.getByTestId('record-payment-amount').fill(amount);
  const saved = page.waitForResponse((r) => r.url().includes('/customer/retailer/payment/record/'));
  await page.getByTestId('record-payment-submit').click();
  return saved;
}

test.describe('Journey C - khata payments (C1 at R1, opening 500)', { tag: ['@retailer', '@khata'] }, () => {
  test.beforeEach(async ({ page, seed }) => {
    await retailerLogin(page);
    await openKhata(page, seed.customers.C1);
    await expect.poll(() => balanceOnScreen(page)).toBe(500);
  });

  test('C1 pay 200: outstanding 300, ledger credit 200, R2 stays 1000', async ({ page, api, seed, retailerToken }) => {
    expect((await recordPayment(page, '200')).status()).toBeLessThan(300);
    await expect.poll(() => balanceOnScreen(page)).toBe(300);

    const r1 = await retailerToken();
    expect(await khataBalance(api, r1, seed.customers.C1)).toBe(300);
    const ledger = await getJson(api, `customer/retailer/ledger/${seed.customers.C1}/`, r1);
    expect(ledger.results).toHaveLength(1);
    expect(Number(ledger.results[0].amount)).toBe(200);
    expect(await khataBalance(api, await retailerToken(R2.username), seed.customers.C1)).toBe(1000);
  });

  test('C2 pay full 500: outstanding 0, khata still visible', async ({ page }) => {
    expect((await recordPayment(page, '500')).status()).toBeLessThan(300);
    await expect.poll(() => balanceOnScreen(page)).toBe(0);
    await page.reload();
    await expect(page.getByTestId('customer-current-balance')).toBeVisible();
    await expect(page.getByTestId('customer-credit-limit')).toBeVisible();
    await expect(page.getByTestId('record-payment-open')).toBeVisible();
  });

  test('C3 zero or negative payment is blocked, balance stays 500', async ({ page, api, seed, retailerToken }) => {
    await page.getByTestId('record-payment-open').click();
    for (const amount of ['0', '-50']) {
      await page.getByTestId('record-payment-amount').fill(amount);
      await expect(page.getByTestId('record-payment-submit')).toBeDisabled();
    }
    // The API refuses it too, for any client that skips the form.
    const r1 = await retailerToken();
    for (const amount of [0, -50]) {
      const response = await api.post('customer/retailer/payment/record/', {
        headers: { Authorization: `Bearer ${r1}` },
        data: { customer_id: seed.customers.C1, amount, payment_mode: 'cash' },
      });
      expect(response.status()).toBe(400);
    }
    expect(await khataBalance(api, r1, seed.customers.C1)).toBe(500);
  });

  test('C4 overpay 600: accepted means advance -100, rejected means 500 unchanged, never a 5xx', async ({ page, api, seed, retailerToken }) => {
    // CASES.md C4: QA does not pick the rule (reject vs advance), but the balance must match the answer.
    const r1 = await retailerToken();
    const ledgerRows = async () => (await getJson(api, `customer/retailer/ledger/${seed.customers.C1}/`, r1)).results.length;
    const rowsBefore = await ledgerRows();
    const response = await recordPayment(page, '600');
    const status = response.status();
    const balance = await khataBalance(api, r1, seed.customers.C1);
    test.info().annotations.push({ type: 'current-behaviour', description: `overpay 600 on 500: HTTP ${status}, balance now ${balance}` });
    expect(status, 'overpay must never be a 5xx').toBeLessThan(500);
    expect(balance).toBe(status < 300 ? -100 : 500);
    if (status >= 400) expect(await ledgerRows(), 'a rejected overpay writes no ledger row').toBe(rowsBefore);
  });
});

test('C5 regression (OE-61): R2 view of C1 shows 1000 with credit_limit 0, no R1 numbers @retailer @khata', async ({ page, seed }) => {
  await retailerLogin(page, R2.username);
  await openKhata(page, seed.customers.C1);
  await expect.poll(() => balanceOnScreen(page)).toBe(1000);
  expect(rupees(await page.getByTestId('customer-credit-limit').textContent())).toBe(0);
  await expect(page.getByTestId('record-payment-open')).toBeVisible();
  await expect(page.getByText(/5,?000/)).toHaveCount(0);
  await expect(page.getByTestId('customer-current-balance')).not.toContainText('500.00');
});
