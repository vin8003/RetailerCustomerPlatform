import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { customerLogin, customerToken, djangoShell, getJson, latestOtp, loginStatus } from '../helpers';
import { PASSWORD } from '../env';
import { C1_MOBILE, C2_MOBILE, SEED, mobile } from '../seed';

const NEW = SEED.signup.customer;
const NEW_MOBILE = mobile(NEW.phone);
const NEW_PASSWORD = SEED.new_password;
const C1 = SEED.customers.C1;

async function fillLogin(page: Page, phone10: string, password: string) {
  await page.goto(`${urls.customer}/login`);
  await page.getByTestId('customer-login-phone').fill(phone10);
  await page.getByTestId('customer-login-password').fill(password);
  await page.getByTestId('customer-login-submit').click();
}

const sessionTokens = (page: Page) =>
  page.evaluate(() => [localStorage.getItem('customer_access_token'), localStorage.getItem('customer_refresh_token')]);

test.describe('Phase 2 - customer auth & account', { tag: ['@customer', '@auth'] }, () => {
  test('C-AUTH1 signup, verify email with the OTP, lands logged in', async ({ page, api }) => {
    await page.goto(`${urls.customer}/signup`);
    await page.getByTestId('customer-signup-email').fill(NEW.email);
    await page.getByTestId('customer-signup-phone').fill(NEW_MOBILE);
    await page.getByTestId('customer-signup-password').fill(PASSWORD);
    await page.getByTestId('customer-signup-confirm').fill(PASSWORD);
    await page.getByTestId('customer-signup-submit').click();
    await page.waitForURL('**/verify-email**');

    await page.getByTestId('verify-email-otp').fill(latestOtp('email', NEW_MOBILE));
    await page.getByTestId('verify-email-submit').click();
    await expect(page.getByTestId('verify-email-success')).toBeVisible();
    await page.waitForURL((url) => !url.pathname.startsWith('/verify-email'));
    expect((await sessionTokens(page))[0]).toBeTruthy();

    const profile = await getJson(api, 'auth/profile/', await customerToken(api, NEW_MOBILE));
    expect(profile.email).toBe(NEW.email);
    expect(profile.is_email_verified ?? true).toBe(true);
  });

  test('C-AUTH2 login with an unverified email is sent to verify-email, no session', async ({ page }) => {
    djangoShell(
      `from authentication.models import User\nUser.objects.filter(username=${JSON.stringify(C1.username)}).update(is_email_verified=False)\n`,
    );
    await fillLogin(page, C1_MOBILE, PASSWORD);
    await page.waitForURL('**/verify-email**');
    expect(decodeURIComponent(page.url())).toContain(`${C1.username}@e2e.invalid`);
    expect((await sessionTokens(page))[0]).toBeNull();
  });

  test('C-AUTH3 wrong password shows an error and leaves no session', async ({ page, api }) => {
    await fillLogin(page, C2_MOBILE, 'Wrong-Pass-000!');
    await expect(page.getByTestId('customer-login-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    expect((await sessionTokens(page))[0]).toBeNull();
    expect(await loginStatus(api, 'auth/customer/login/', `+91${C2_MOBILE}`, 'Wrong-Pass-000!')).toBeGreaterThanOrEqual(400);
  });

  test('C-AUTH4 email password reset with the OTP: old password fails, new one logs in', async ({ page, api }) => {
    await page.goto(`${urls.customer}/forgot-password`);
    await page.getByTestId('customer-forgot-email').fill(`${C1.username}@e2e.invalid`);
    await page.getByTestId('customer-forgot-send').click();
    await expect(page.getByTestId('customer-reset-otp')).toBeVisible();

    await page.getByTestId('customer-reset-otp').fill(latestOtp('email', C1.username));
    await page.getByTestId('customer-reset-password').fill(NEW_PASSWORD);
    await page.getByTestId('customer-reset-confirm').fill(NEW_PASSWORD);
    await page.getByTestId('customer-reset-submit').click();
    await expect(page.getByTestId('customer-forgot-success')).toBeVisible();

    expect(await loginStatus(api, 'auth/customer/login/', `+91${C1_MOBILE}`, PASSWORD)).toBeGreaterThanOrEqual(400);
    await fillLogin(page, C1_MOBILE, NEW_PASSWORD);
    await page.waitForURL((url) => !url.pathname.startsWith('/login'));
    expect((await sessionTokens(page))[0]).toBeTruthy();
  });

  test('C-AUTH5 profile edit is saved and shown on the profile page', async ({ page, api }) => {
    await customerLogin(page, C2_MOBILE);
    await page.goto(`${urls.customer}/profile/edit`);
    await expect(page.getByTestId('profile-first-name')).toHaveValue(SEED.customers.C2.first_name);
    await page.getByTestId('profile-first-name').fill('Renamed');
    await page.getByTestId('profile-last-name').fill('Customer');
    const saved = page.waitForResponse((r) => r.url().includes('/customer/profile/update/'));
    await page.getByTestId('profile-save').click();
    expect((await saved).status()).toBe(200);

    const profile = await getJson(api, 'auth/profile/', await customerToken(api, C2_MOBILE));
    expect([profile.first_name, profile.last_name]).toEqual(['Renamed', 'Customer']);
    await page.goto(`${urls.customer}/profile`);
    await expect(page.getByTestId('profile-name')).toHaveText(/Renamed\s+Customer/);
  });
});
