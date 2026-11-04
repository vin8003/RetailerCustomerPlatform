import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { known } from '../edge';
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
  test('F1 customer wrong password: stays on /login, error shown, no token stored', { tag: '@customer', ...known('OE-393', 'customer login shows the generic error on a 400 non_field_errors') }, async ({ page }) => {
    const res = await customerTry(page, C1_MOBILE, 'WrongPass999!');
    // Backend: 400 {non_field_errors:['Invalid credentials']}; the customer FE shows `detail` or, on 401,
    // its own text, so a 400 without `detail` falls through to the generic message.
    expect(res.status()).toBe(400);
    expect(await res.json()).toMatchObject({ non_field_errors: ['Invalid credentials'] });
    await expect(page.getByTestId('customer-login-error')).toHaveText('An unexpected error occurred. Please try again.');
    await expect(page).toHaveURL(/\/login/);
    const stored = await page.evaluate(() => JSON.stringify(localStorage));
    expect(stored).not.toMatch(/eyJ[\w-]+\.eyJ/);
  });

  test('F2 customer unknown phone: same error path, still on /login', { tag: '@customer', ...known('OE-393', 'customer login shows the generic error on a 400 non_field_errors') }, async ({ page }) => {
    const res = await customerTry(page, '9000000001', 'Whatever123!');
    // Backend: 400 {non_field_errors:['Invalid credentials']}; the customer FE shows `detail` or, on 401,
    // its own text, so a 400 without `detail` falls through to the generic message.
    expect(res.status()).toBe(400);
    expect(await res.json()).toMatchObject({ non_field_errors: ['Invalid credentials'] });
    await expect(page.getByTestId('customer-login-error')).toHaveText('An unexpected error occurred. Please try again.');
    await expect(page).toHaveURL(/\/login/);
  });

  test('F3 retailer wrong password: error toast, no dashboard', { tag: '@retailer' }, async ({ page }) => {
    await page.goto(`${urls.retailer}/login`);
    await page.getByTestId('login-username').fill(R1.username);
    await page.getByTestId('login-password').fill('WrongPass999!');
    const answered = page.waitForResponse((r) => r.url().includes('/retailer/login/') && r.request().method() === 'POST');
    await page.getByTestId('login-submit').click();
    // Backend: 400 {non_field_errors:['Invalid credentials']}; no `detail`, so the retailer FE toasts its fallback.
    const res = await answered;
    expect(res.status()).toBe(400);
    expect(await res.json()).toMatchObject({ non_field_errors: ['Invalid credentials'] });
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password');
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
