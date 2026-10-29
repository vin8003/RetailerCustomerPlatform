/**
 * Store settings: operating hours, slot capacity, delivery/COD/minimum order, staff and roles,
 * notification preferences. Staff, roles and notification prefs have no retailer UI yet, so they are API-only.
 * seed_e2e resets hours (10–12 daily), profile flags, capacity, e2es_ staff, custom roles and notification config.
 */
import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { authed, customerToken, getJson, retailerLogin, sl1 } from '../helpers';
import { placeOrder, tryPlaceOrder } from '../edge';
import { C2_MOBILE } from '../seed';

const PASSWORD = 'E2e-Pass-123!';
const tomorrowIst = () => new Date(Date.now() + 5.5 * 3600e3 + 24 * 3600e3);
const slotDates = async (api: Parameters<typeof getJson>[0], ct: string, retailerId: number) =>
  new Set((await getJson(api, `retailers/${retailerId}/fulfillment-slots/?delivery_mode=delivery`, ct)).slots
    .map((s: { slot_start_local: string }) => s.slot_start_local.slice(0, 10)));

async function profileSwitch(page: Page, label: string) {
  await page.goto(`${urls.retailer}/dashboard/profile`);
  await page.getByRole('button', { name: 'Edit Profile' }).click();
  await page.locator('div.justify-between', { hasText: label }).last().getByRole('switch').click();
  const saved = page.waitForResponse((r) => r.url().includes('profile/update') && r.request().method() !== 'GET');
  await page.getByRole('button', { name: 'Save Changes' }).click();
  expect((await saved).status()).toBe(200);
}

test.describe('Settings - store', { tag: ['@settings', '@retailer'] }, () => {
  test('S1 closing tomorrow in operating hours removes tomorrow\'s slots for customers', async ({ page, api, seed }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const date = tomorrowIst().toISOString().slice(0, 10);
    expect(await slotDates(api, ct, seed.retailers.R1)).toContain(date);
    const day = tomorrowIst().toLocaleDateString('en-US', { weekday: 'long', timeZone: 'UTC' });

    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/operating-hours`);
    const row = page.locator('div.bg-card.rounded-lg', { hasText: day });
    await row.getByRole('switch').click();
    await expect(row.getByText('Closed')).toBeVisible();
    const saved = page.waitForResponse((r) => r.url().includes('operating-hours') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Save Changes' }).click();
    expect((await saved).status()).toBe(200);
    await expect(page.getByText('Operating hours updated successfully')).toBeVisible();

    expect(await slotDates(api, ct, seed.retailers.R1)).not.toContain(date);
    await page.reload();
    await expect(page.locator('div.bg-card.rounded-lg', { hasText: day }).getByText('Closed')).toBeVisible();
  });

  test('S2 slot capacity set to 1 in the UI fills the slot after one order', async ({ page, api, seed }) => {
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/operating-hours`);
    const capacity = page.locator('#slotCapacity');
    await expect(capacity).toHaveValue('10'); // seeded value loaded, so our fill is not overwritten
    await capacity.fill('1');
    await page.getByRole('button', { name: 'Save capacity' }).click();
    await expect(page.getByText('Fulfillment slot capacity updated')).toBeVisible();

    const ct = await customerToken(api, C2_MOBILE);
    await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const slots = await getJson(api, `retailers/${seed.retailers.R1}/fulfillment-slots/?delivery_mode=delivery`, ct);
    const slot = slots.slots.find((s: { slot_start_local: string }) => s.slot_start_local === sl1().start);
    expect(slot?.is_available ?? false).toBe(false);
  });

  test('S3 turning delivery off in the profile refuses delivery orders', async ({ page, api, seed }) => {
    await retailerLogin(page);
    await profileSwitch(page, 'Offers Delivery');
    const ct = await customerToken(api, C2_MOBILE);
    const r = await tryPlaceOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address, slotStart: `${sl1().start}` });
    expect(r.status()).toBe(400);
    expect(await r.text()).toContain('This retailer does not offer delivery.');
  });

  test('S4 turning COD off in the profile refuses cash orders', async ({ page, api, seed }) => {
    await retailerLogin(page);
    await profileSwitch(page, 'Accept Cash (COD)');
    const ct = await customerToken(api, C2_MOBILE);
    const r = await tryPlaceOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    expect(r.status()).toBe(400);
    expect(await r.text()).toContain('This retailer does not accept Cash on Delivery.');
  });

  test('S5 a minimum order amount refuses smaller orders', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    expect((await api.patch('retailers/profile/update/', { ...authed(rt), data: { minimum_order_amount: '500' } })).status()).toBe(200);
    const ct = await customerToken(api, C2_MOBILE);
    const r = await tryPlaceOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    expect(r.status()).toBe(400);
    expect(await r.text()).toContain('Minimum order amount is ₹500.00');
  });
});

test.describe('Settings - staff, roles, notifications', { tag: ['@settings', '@retailer'] }, () => {
  test('S6 a staff member with orders.read can read orders but not change them or the store', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const org = (await getJson(api, 'retailers/profile/', rt)).organization_id;
    const role = await api.post(`retailers/org/${org}/roles/`, { ...authed(rt), data: { name: 'E2E Packer', slug: 'e2e-packer', permissions: ['orders.read'] } });
    expect(role.status(), await role.text()).toBe(201);
    const staff = await api.post(`retailers/org/${org}/staff/`, { ...authed(rt), data: { role_id: (await role.json()).id, username: 'e2es_packer', password: PASSWORD } });
    expect(staff.status(), await staff.text()).toBe(201);
    const login = await (await api.post('auth/retailer/login/', { data: { username: 'e2es_packer', password: PASSWORD } })).json();
    const st: string = login.tokens?.access ?? login.access;

    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    expect((await api.get('orders/inbox/', authed(st))).status()).toBe(200);
    expect((await api.get(`orders/${order.id}/`, authed(st))).status()).toBe(200);
    expect((await api.patch(`orders/${order.id}/status/`, { ...authed(st), data: { status: 'confirmed' } })).status()).toBe(403);
    expect((await api.post(`retailers/org/${org}/roles/`, { ...authed(st), data: { name: 'x', slug: 'e2e-x', permissions: [] } })).status()).toBe(403);
    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('pending');

    const roles = await getJson(api, `retailers/org/${org}/roles/`, rt);
    expect(JSON.stringify(roles)).toContain('e2e-packer');
    const members = await getJson(api, `retailers/org/${org}/staff/`, rt);
    expect(JSON.stringify(members)).toContain('e2es_packer');
  });

  test('S7 notification preferences: owner can disable a type, unknown types and staff are refused', async ({ api, retailerToken }) => {
    const rt = await retailerToken();
    const org = (await getJson(api, 'retailers/profile/', rt)).organization_id;
    const path = `retailers/org/${org}/notifications/config/`;
    expect(await getJson(api, path, rt)).toMatchObject({ default_channel: 'push', disabled_types: [] });

    const ok = await api.patch(path, { ...authed(rt), data: { disabled_types: ['order.status.confirmed'] } });
    expect(ok.status(), await ok.text()).toBe(200);
    expect((await getJson(api, path, rt)).disabled_types).toEqual(['order.status.confirmed']);
    expect((await api.patch(path, { ...authed(rt), data: { disabled_types: ['not.a.type'] } })).status()).toBe(400);

    const role = await (await api.post(`retailers/org/${org}/roles/`, { ...authed(rt), data: { name: 'E2E Reader', slug: 'e2e-reader', permissions: ['orders.read'] } })).json();
    expect((await api.post(`retailers/org/${org}/staff/`, { ...authed(rt), data: { role_id: role.id, username: 'e2es_reader', password: PASSWORD } })).status()).toBe(201);
    const login = await (await api.post('auth/retailer/login/', { data: { username: 'e2es_reader', password: PASSWORD } })).json();
    const st: string = login.tokens?.access ?? login.access;
    expect((await api.patch(path, { ...authed(st), data: { default_channel: 'sms' } })).status()).toBe(403);
    expect((await getJson(api, path, rt)).default_channel).toBe('push');
  });
});
