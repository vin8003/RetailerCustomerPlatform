/** Helpers for the catalog / offers / inventory slice specs. Names made here start with E2EC / E2EO / E2EI. */
import { type APIRequestContext, type Page } from '@playwright/test';
import { expect, urls } from './fixtures';
import { authed, customerLogin, customerUseSeedCity, getJson } from './helpers';


export const bug = (description: string) => ({ annotation: { type: 'bug', description } });

export async function post(api: APIRequestContext, path: string, token: string, data: unknown, status = 201) {
  const response = await api.post(path, { ...authed(token), data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(status);
  return response.json();
}

export async function patch(api: APIRequestContext, path: string, token: string, data: unknown) {
  const response = await api.patch(path, { ...authed(token), data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(200);
  return response.json();
}

/** List results whether the endpoint pages or not. */
export function rows(body: { results?: unknown[] } | unknown[]): Record<string, any>[] {
  return (Array.isArray(body) ? body : body.results ?? []) as Record<string, any>[];
}

export async function retailerProducts(api: APIRequestContext, token: string, query: string) {
  return rows(await getJson(api, `products/?${query}`, token));
}

export async function customerProducts(api: APIRequestContext, token: string, retailerId: number, query: string) {
  return rows(await getJson(api, `products/retailer/${retailerId}/?${query}`, token));
}

export async function createProduct(api: APIRequestContext, token: string, data: Record<string, unknown>) {
  return post(api, 'products/create/', token, { unit: 'piece', ...data });
}

export async function applyCoupon(api: APIRequestContext, token: string, retailerId: number, code: string) {
  return api.post('cart/apply-coupon/', { ...authed(token), data: { retailer_id: retailerId, coupon_code: code } });
}

/** Customer C2 signed in, seed city chosen, shopping at `retailerId`. */
export async function customerAtShop(page: Page, phone10: string, retailerId: number) {
  await customerUseSeedCity(page);
  await customerLogin(page, phone10);
  await page.evaluate((id) => localStorage.setItem('current_retailer_id', String(id)), retailerId);
}

export const customerUrl = (path: string) => `${urls.customer}${path}`;
export const retailerUrl = (path: string) => `${urls.retailer}${path}`;
