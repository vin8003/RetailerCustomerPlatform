import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { getJson, latestOtp, loginStatus, retailerLogin } from '../helpers';
import { PASSWORD } from '../env';
import { C1_MOBILE, R1, R2, SEED, mobile } from '../seed';

const NEW = SEED.signup.retailer;
const ADMIN = SEED.admin;
const PENDING = SEED.pending_retailer;
const NEW_PASSWORD = SEED.new_password;

async function fillLogin(page: Page, username: string, password: string) {
  await page.goto(`${urls.retailer}/login`);
  await page.getByTestId('login-username').fill(username);
  await page.getByTestId('login-password').fill(password);
  await page.getByTestId('login-submit').click();
}

async function expectStillLoggedOut(page: Page) {
  await expect(page.getByText(/invalid|not|denied|credentials|retailer/i).first()).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
  expect(await page.evaluate(() => Object.keys(localStorage).filter((k) => /token/i.test(k)))).toEqual([]);
}

test.describe('Phase 2 - retailer auth & account', { tag: ['@retailer', '@auth'] }, () => {
  test('R-AUTH1 signup lands on the dashboard with a pending-approval banner and a pending profile', async ({ page, api }) => {
    await page.goto(`${urls.retailer}/signup`);
    await page.getByTestId('signup-username').fill(NEW.username);
    await page.getByTestId('signup-email').fill(NEW.email);
    await page.getByTestId('signup-phone').fill(mobile(NEW.phone));
    await page.getByTestId('signup-password').fill(PASSWORD);
    await page.getByTestId('signup-confirm-password').fill(PASSWORD);
    await page.getByTestId('signup-submit').click();
    await page.waitForURL('**/dashboard**');
    await expect(page.getByTestId('verification-banner')).toHaveAttribute('data-status', 'pending');

    const login = await api.post('auth/retailer/login/', { data: { username: NEW.username, password: PASSWORD } });
    expect(login.status(), await login.text()).toBe(200);
    const token = (await login.json()).tokens.access;
    const profile = await getJson(api, 'retailer/profile/', token);
    expect(profile.verification_status).toBe('pending');
  });

  test('R-AUTH2 admin approves a pending retailer in the UI; the retailer first login has no banner', async ({ page, api, retailerToken }) => {
    await retailerLogin(page, PENDING.username);
    await expect(page.getByTestId('verification-banner')).toHaveAttribute('data-status', 'pending');
    await page.evaluate(() => localStorage.clear());

    await retailerLogin(page, ADMIN.username);
    await page.goto(`${urls.retailer}/dashboard/admin/verifications`);
    const card = page.locator(`[data-testid="verification-card"][data-username="${PENDING.username}"]`);
    const approved = page.waitForResponse((r) => /admin\/verifications\/\d+\/action\//.test(r.url()) && r.request().method() === 'POST');
    await card.getByTestId('verification-approve').click();
    expect((await approved).status()).toBe(200);

    const profile = await getJson(api, 'retailer/profile/', await retailerToken(PENDING.username));
    expect(profile.verification_status).toBe('approved');

    await page.evaluate(() => localStorage.clear());
    await retailerLogin(page, PENDING.username);
    await expect(page.getByTestId('profile-logout').or(page.locator('main'))).toBeVisible();
    await expect(page.getByTestId('verification-banner')).toHaveCount(0);
  });

  test('R-AUTH3 wrong password is refused and leaves no session', async ({ page, api }) => {
    await fillLogin(page, R1.username, 'Wrong-Pass-000!');
    await expectStillLoggedOut(page);
    expect(await loginStatus(api, 'auth/retailer/login/', R1.username, 'Wrong-Pass-000!')).toBeGreaterThanOrEqual(400);
  });

  test('R-AUTH4 customer credentials are refused by the retailer app', async ({ page, api }) => {
    await fillLogin(page, SEED.customers.C1.username, PASSWORD);
    await expectStillLoggedOut(page);
    expect(await loginStatus(api, 'auth/retailer/login/', `+91${C1_MOBILE}`, PASSWORD)).toBeGreaterThanOrEqual(400);
  });

  // BUG (report for Jira): on /forgot-password step 2 the Code input stays empty; typed digits never stick, so the reset cannot be submitted.
  test.fixme('R-AUTH5 password reset with the OTP: old password stops working, new one logs in', async ({ page, api }) => {
    await page.goto(`${urls.retailer}/forgot-password`);
    await page.getByTestId('forgot-identifier').fill(R2.username);
    const sent = page.waitForResponse((r) => r.url().includes('password/forgot/') && r.ok());
    await page.getByTestId('forgot-send').click();
    await sent;
    const otp = latestOtp('phone', R2.username);
    await expect(page.getByTestId('reset-code')).toBeEditable();
    await page.getByTestId('reset-code').fill(otp);
    await expect(page.getByTestId('reset-code')).toHaveValue(otp);
    await page.getByTestId('reset-new-password').fill(NEW_PASSWORD);
    await page.getByTestId('reset-confirm-password').fill(NEW_PASSWORD);
    await page.getByTestId('reset-submit').click();
    await page.waitForURL('**/login');

    expect(await loginStatus(api, 'auth/retailer/login/', R2.username, PASSWORD)).toBeGreaterThanOrEqual(400);
    await fillLogin(page, R2.username, NEW_PASSWORD);
    await page.waitForURL('**/dashboard**');
  });

  test('R-AUTH6 shop profile edit is saved to the backend', async ({ page, api, retailerToken }) => {
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/profile`);
    await page.getByTestId('profile-edit').click();
    await page.getByTestId('profile-shop-name').fill('E2E Kirana Renamed');
    await page.getByTestId('profile-city').fill('Gurugram');
    const saved = page.waitForResponse((r) => r.url().includes('/retailer/profile/update/'));
    await page.getByTestId('profile-save').click();
    expect((await saved).status()).toBe(200);

    const profile = await getJson(api, 'retailer/profile/', await retailerToken());
    expect(profile.shop_name).toBe('E2E Kirana Renamed');
    expect(profile.city).toBe('Gurugram');
  });
});
