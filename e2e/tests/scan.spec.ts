/**
 * Slice scan: the mobile POS camera scanner, fed by Chromium's fake camera.
 * The fake camera plays a generated EAN-13 clip of SFB Rice 1kg; html5-qrcode decodes it
 * exactly as it would a real phone camera, and the bill gets the product.
 */
import { join } from 'node:path';
import { devices } from '@playwright/test';
import { test, expect } from '../fixtures';
import { getJson, posCheckoutResponse, retailerLogin } from '../helpers';
import { PASSWORD } from '../env';
import { SFB_PRODUCT, SFB_RETAILER, sfbIds, sfbRetailerToken, stock, writeBarcodeY4m } from '../sfb';

const fixme = process.env.E2E_RUN_FIXME ? test : test.fixme;

const CLIP = writeBarcodeY4m(SFB_PRODUCT.RICE.barcode, join(__dirname, '..', 'test-results', 'fake-camera', 'sfb-rice.y4m'));

test.use({
  ...devices['Pixel 7'],
  defaultBrowserType: 'chromium',
  launchOptions: {
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${CLIP}`],
  },
  permissions: ['camera'],
});

test.describe('Slice scan - mobile POS camera scan', { tag: ['@slice-scan', '@retailer', '@pos'] }, () => {
  test('SC1 camera scan adds the product to the bill; tap Scan adds it again; bill saves and stock drops', async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    await retailerLogin(page, SFB_RETAILER.username);
    await page.goto('/dashboard/pos');
    await expect(page.getByText(SFB_PRODUCT.RICE.name).first()).toBeVisible();

    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    // Tap Scan with the code in view, like a counter scanner's trigger: each tap adds one.
    // (The first code is meant to be read without a tap; that is SC2, fixme.)
    const scan = page.getByRole('button', { name: 'Scan', exact: true });
    const bar = page.getByRole('button', { name: /^\d+ items? ₹/ });
    await expect(async () => {
      await scan.click();
      await expect(page.getByText(`Added ${SFB_PRODUCT.RICE.name}`).first()).toBeVisible({ timeout: 1000 });
    }).toPass();
    await page.getByRole('button', { name: 'Close scanner' }).click();
    await expect(bar).toHaveText(/1 item\s*₹100/);
    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    await expect(async () => {
      await scan.click();
      await expect(page.getByText(`Added ${SFB_PRODUCT.RICE.name}`).first()).toBeVisible({ timeout: 1000 });
    }).toPass();
    await page.getByRole('button', { name: 'Close scanner' }).click();
    // Same product twice: one line, quantity 2.
    await expect(bar).toHaveText(/1 item\s*₹200/);

    await bar.click();
    await expect(page.getByTestId('pos-total')).toHaveText('₹200');
    await page.getByTestId('pos-pay-cash').click();
    const checkout = posCheckoutResponse(page);
    // Phone layout: the sticky bottom button (pos-complete-bill is the desktop one, hidden here).
    await page.getByRole('button', { name: 'COMPLETE BILL', exact: true }).click();
    const response = await checkout;
    expect(response.status(), await response.text()).toBe(201);
    const { order } = await response.json();
    await expect(page.getByTestId('pos-paid-total')).toHaveText('₹200');

    const token = await sfbRetailerToken(api, PASSWORD);
    const saved = await getJson(api, `orders/${order.id}/`, token);
    expect(saved.total_amount).toBe('200.00');
    expect(saved.items.map((i: { product: number; quantity: number }) => [i.product, Number(i.quantity)]))
      .toEqual([[ids.products.RICE, 2]]);
    expect(await stock(api, token, ids.products.RICE)).toBe(Number(SFB_PRODUCT.RICE.stock) - 2);
  });

  // BUG: the first code is never auto-read in next dev (React StrictMode mounts BarcodeScanner twice; the
  // zombie scanner is not stopped, keeps a 2nd camera stream and its callback sets the shared firstCodeTaken ref).
  fixme('SC2 first code in view is added without a tap @slice-scan', async ({ page }) => {
    test.info().annotations.push({ type: 'bug', description: 'BarcodeScanner: cleanup does not stop the first Html5Qrcode; auto-read swallowed' });
    await retailerLogin(page, SFB_RETAILER.username);
    await page.goto('/dashboard/pos');
    await expect(page.getByText(SFB_PRODUCT.RICE.name).first()).toBeVisible();
    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    await expect(page.getByText(`Added ${SFB_PRODUCT.RICE.name}`).first()).toBeVisible();
    await page.getByRole('button', { name: 'Close scanner' }).click();
    await expect(page.getByRole('button', { name: /^\d+ items? ₹/ })).toHaveText(/1 item\s*₹100/);
  });
});
