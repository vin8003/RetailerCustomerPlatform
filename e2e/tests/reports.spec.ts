/**
 * Retailer reports: today's sales summary (POS + online, by payment mode) and dashboard stats,
 * checked against a seeded day. No GST, stock or khata report, date filter or export exists yet.
 */
import { type APIRequestContext } from '@playwright/test';
import { test, expect, urls, type SeedIds } from '../fixtures';
import { authed, customerToken, getJson, retailerLogin } from '../helpers';
import { advance, fixme, known, placeOrder, posBill } from '../edge';
import { C1_MOBILE, C2_MOBILE, SEED } from '../seed';

/**
 * POS cash P3 165 + POS UPI P2 140 + POS credit P4×2 60 (C1) + delivered online COD P5 100
 * + a cancelled online P1 250 (excluded) = 465 over 4 orders.
 */
async function seedDay(api: APIRequestContext, seed: SeedIds, rt: string) {
  const C1 = { mobile: C1_MOBILE, name: SEED.customers.C1.first_name };
  expect((await posBill(api, rt, [[seed.products.P3, 1, 'P3']], { cash: 165 })).status()).toBe(201);
  expect((await posBill(api, rt, [[seed.products.P2, 1, 'P2']], { upi: 140 })).status()).toBe(201);
  expect((await posBill(api, rt, [[seed.products.P4, 2, 'P4']], { credit: 60 }, C1)).status()).toBe(201);
  const ct = await customerToken(api, C2_MOBILE);
  const delivered = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P5, 1]], { addressId: seed.c2_address });
  await advance(api, rt, delivered.id, ['confirmed', 'processing', 'packed', 'out_for_delivery', 'delivered']);
  const cancelled = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P1, 1]], { addressId: seed.c2_address });
  expect((await api.post(`orders/${cancelled.id}/cancel/`, { ...authed(ct), data: { reason: 'E2E report' } })).status()).toBe(200);
  return ct;
}

const EXPECTED = {
  total_sales: 465, order_count: 4, cash_sales: 265, digital_sales: 140,
  credit_sales: 60, pos_sales: 365, online_sales: 100,
};

test.describe('Reports', { tag: ['@reports', '@retailer'] }, () => {
  test('R1 daily sales summary splits a seeded day by payment mode and channel', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    await seedDay(api, seed, rt);
    const summary = await getJson(api, 'products/erp/daily-sales-summary/', rt);
    expect(summary).toMatchObject({ ...EXPECTED, shop_name: SEED.retailers.R1.shop_name, cash_refunds: 0, upi_refunds: 0 });
  });

  test('R2 dashboard stats agree with the summary and count the cancelled order separately', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    await seedDay(api, seed, rt);
    const stats = await getJson(api, 'orders/stats/', rt);
    expect(stats).toMatchObject({
      total_orders: 5, delivered_orders: 4, cancelled_orders: 1, pending_orders: 0,
      total_revenue: '465.00', today_revenue: '465.00', average_order_value: '116.25',
      cash_sales: '265.00', digital_sales: '140.00', credit_sales: '60.00', pos_sales: '365.00', online_sales: '100.00',
    });
  });

  test('R3 the reports page shows the seeded totals', async ({ page, api, seed, retailerToken }) => {
    const rt = await retailerToken();
    await seedDay(api, seed, rt);
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/reports`);
    await expect(page.getByRole('heading', { name: '₹465' })).toBeVisible();
    await expect(page.getByText('4 Orders Processed')).toBeVisible();
    const value = (label: string) => page.locator(`xpath=//p[normalize-space()='${label}']/following::p[1]`);
    await expect(value('Cash in Hand')).toHaveText('₹265');
    await expect(value('Digital Payments')).toHaveText('₹140');
    await expect(value('POS Sales')).toHaveText('₹365');
    await expect(value('Online Store')).toHaveText('₹100');
  });

  fixme('R4 an order that is still pending is not counted as a sale',
    known('OE-382', 'daily-sales-summary counts a pending online COD order (total 495, cash 295) while orders/stats says 465'),
    async ({ api, seed, retailerToken }) => {
      const rt = await retailerToken();
      const ct = await seedDay(api, seed, rt);
      await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
      const summary = await getJson(api, 'products/erp/daily-sales-summary/', rt);
      expect(summary).toMatchObject(EXPECTED);
    });
});
