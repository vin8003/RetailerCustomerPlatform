import { type APIRequestContext, type Page, type Response } from '@playwright/test';
import { execSync } from 'node:child_process';
import { expect, urls } from './fixtures';
import { MANAGE_CMD, PASSWORD } from './env';

export async function retailerLogin(page: Page, username = 'e2e_retailer') {
  await page.goto(`${urls.retailer}/login`);
  await page.getByTestId('login-username').fill(username);
  await page.getByTestId('login-password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL('**/dashboard**');
}

export async function customerLogin(page: Page, phone10: string) {
  await page.goto(`${urls.customer}/login`);
  await page.getByTestId('customer-login-phone').fill(phone10);
  await page.getByTestId('customer-login-password').fill(PASSWORD);
  await page.getByTestId('customer-login-submit').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
}

/** "₹1,120.00" / "₹620" -> 1120 */
export function rupees(text: string | null): number {
  return Number((text ?? '').replace(/[^0-9.-]/g, ''));
}

export function authed(token: string) {
  return { headers: { Authorization: `Bearer ${token}` } };
}

export async function getJson(api: APIRequestContext, path: string, token: string) {
  const response = await api.get(path, authed(token));
  expect(response.status(), `${path}: ${await response.text()}`).toBe(200);
  return response.json();
}

export async function khataBalance(api: APIRequestContext, token: string, customerId: number): Promise<number> {
  const body = await getJson(api, `customer/retailer/details/${customerId}/`, token);
  return Number(body.current_balance);
}

export async function productStock(api: APIRequestContext, token: string, productId: number): Promise<number> {
  const body = await getJson(api, `products/${productId}/`, token);
  return Number(body.quantity);
}

/** Wait for the POS checkout API call that a click triggers. */
export function posCheckoutResponse(page: Page): Promise<Response> {
  return page.waitForResponse((r) => r.url().includes('/erp/pos-checkout/') && r.request().method() === 'POST');
}

/** The customer app lists retailers for the city saved in localStorage; seed shops are in New Delhi. */
export async function customerUseSeedCity(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('selected_city', JSON.stringify({ id: 'new-delhi_delhi', name: 'New Delhi', state: 'Delhi' }));
  });
}

export async function customerToken(api: APIRequestContext, phone10: string): Promise<string> {
  const response = await api.post('auth/customer/login/', { data: { username: `+91${phone10}`, password: PASSWORD } });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()).tokens.access;
}

export async function addToCart(api: APIRequestContext, token: string, productId: number, quantity: number) {
  const response = await api.post('cart/add/', { ...authed(token), data: { product_id: productId, quantity } });
  expect(response.status(), await response.text()).toBe(201);
}


/** SL1 (seed): tomorrow 10:00 IST, offered as 30-minute slots; tests book the first one. */
export function sl1(now = Date.now()) {
  const tomorrow = new Date(now + 24 * 3600 * 1000);
  const part = (opts: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Kolkata', ...opts }).format(tomorrow);
  const ymd = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(tomorrow);
  const weekday = part({ weekday: 'short' });
  const month = part({ month: 'short' });
  const day = part({ day: 'numeric' });
  return {
    start: `${ymd}T10:00:00+05:30`,
    customerLabel: `${weekday}, ${day} ${month}, 10:00 am – 10:30 am`,
    retailerLabel: `${weekday}, ${month} ${day} • 10:00 AM – 10:30 AM`,
  };
}

/** Place a COD delivery order for whatever is in the customer's cart at that retailer, in the SL1 slot. */
export async function placeCodOrder(api: APIRequestContext, token: string, retailerId: number, addressId: number) {
  const slots = await getJson(api, `retailers/${retailerId}/fulfillment-slots/?delivery_mode=delivery`, token);
  const slot = slots.slots.find((s: { slot_start_local: string }) => s.slot_start_local === sl1().start);
  expect(slot, `SL1 slot ${sl1().start} offered`).toBeTruthy();
  const response = await api.post('orders/place/', {
    ...authed(token),
    data: {
      retailer_id: String(retailerId),
      address_id: addressId,
      delivery_mode: 'delivery',
      payment_mode: 'cash',
      special_instructions: '',
      use_reward_points: false,
      coupon_code: null,
      fulfillment_slot_start: slot.slot_start,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  const body = await response.json();
  return body.order ?? body;
}

/** Run a few lines of Django ORM code against the e2e database (fixme setups only). */
export function djangoShell(code: string): string {
  return execSync(`${MANAGE_CMD} shell`, { input: code, encoding: 'utf8', shell: '/bin/bash' });
}

/** Create an offer at the retailer behind `token`; `product` targets one product, otherwise the whole cart. */
export async function createOffer(api: APIRequestContext, token: string, offer: Record<string, unknown>, product?: number) {
  const targets = product ? [{ target_type: 'product', product }] : [{ target_type: 'all_products' }];
  const response = await api.post('offers/', { ...authed(token), data: { benefit_type: 'discount', targets, ...offer } });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

export async function customerCart(api: APIRequestContext, token: string, retailerId: number) {
  return getJson(api, `cart/?retailer_id=${retailerId}`, token);
}
