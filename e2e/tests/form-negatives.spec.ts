import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { customerUseSeedCity, khataBalance, retailerLogin, rupees } from '../helpers';
import { C1_MOBILE, R1 } from '../seed';

// Form negatives: wrong credentials keep you on /login with a plain error; khata over-payment is booked as an advance.

async function customerTry(page: Page, phone: string, password: string) {
  await customerUseSeedCity(page);
  await page.goto(`${urls.customer}/login`);
  await page.getByTestId('customer-login-phone').fill(phone);
  await page.getByTestId('customer-login-password').fill(password);
  const answered = page.waitForResponse((r) => r.url().includes('/customer/login/') && r.request().method() === 'POST');
  await page.getByTestId('customer-login-submit').click();
  return answered;
}

test.describe('Form negatives - login', { tag: ['@form-neg'] }, () => {
  test('F1 customer wrong password: stays on /login, error shown, no token stored', { tag: '@customer' }, async ({ page }) => {
    const res = await customerTry(page, C1_MOBILE, 'WrongPass999!');
    expect(res.status()).toBeGreaterThanOrEqual(400);
    await expect(page.getByTestId('customer-login-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    const stored = await page.evaluate(() => JSON.stringify(localStorage));
    expect(stored).not.toMatch(/eyJ[\w-]+\.eyJ/);
  });

  test('F2 customer unknown phone: same error path, still on /login', { tag: '@customer' }, async ({ page }) => {
    const res = await customerTry(page, '9000000001', 'Whatever123!');
    expect(res.status()).toBeGreaterThanOrEqual(400);
    await expect(page.getByTestId('customer-login-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test('F3 retailer wrong password: error toast, no dashboard', { tag: '@retailer' }, async ({ page }) => {
    await page.goto(`${urls.retailer}/login`);
    await page.getByTestId('login-username').fill(R1.username);
    await page.getByTestId('login-password').fill('WrongPass999!');
    const answered = page.waitForResponse((r) => r.url().includes('/retailer/login/') && r.request().method() === 'POST');
    await page.getByTestId('login-submit').click();
    expect((await answered).status()).toBeGreaterThanOrEqual(400);
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });
});

test('F4 khata: paying more than owed (800 on 500) is booked as an advance of 300 @retailer @khata @form-neg', async ({ page, api, seed, retailerToken }) => {
  await retailerLogin(page);
  await page.goto(`${urls.retailer}/dashboard/customers/details?id=${seed.customers.C1}`);
  await expect.poll(async () => rupees(await page.getByTestId('customer-current-balance').textContent())).toBe(500);
  await page.getByTestId('record-payment-open').click();
  await page.getByTestId('record-payment-amount').fill('800');
  const saved = page.waitForResponse((r) => r.url().includes('/customer/retailer/payment/record/'));
  await page.getByTestId('record-payment-submit').click();
  expect((await saved).status()).toBe(201);
  expect(await khataBalance(api, await retailerToken(), seed.customers.C1)).toBe(-300);
});
