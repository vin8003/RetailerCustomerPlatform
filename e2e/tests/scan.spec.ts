/**
 * Slice scan: the mobile POS camera scanner, fed by Chromium's fake camera.
 * The fake camera plays a generated EAN-13 clip of SFB Rice 1kg; html5-qrcode decodes it
 * exactly as it would a real phone camera, and the bill gets the product.
 */
import { join } from 'node:path';
import { devices } from '@playwright/test';
import { test, expect } from '../fixtures';
import type { Locator, Page } from '@playwright/test';
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

/**
 * One camera scan, ending with the cart bar at `want`. Never adds twice.
 * Opening the scanner may auto-read the first code (OE-386 makes that a race), so first let the
 * scanner settle: at 10 fps it has decoded the code well within 3 s. If it auto-read, we are done.
 * Otherwise the bar must still show what it showed before, and one tap adds the code. A second tap
 * happens only when the app says "No barcode in view" (that tap added nothing).
 */
async function scanOnce(page: Page, bar: Locator, before: RegExp | null, want: RegExp) {
  const autoRead = await expect(bar).toHaveText(want, { timeout: 3000 }).then(() => true, () => false);
  if (autoRead) return;
  if (before) await expect(bar).toHaveText(before);
  else await expect(bar).toHaveCount(0);
  const scan = page.getByRole('button', { name: 'Scan', exact: true });
  const nothing = page.getByText('No barcode in view', { exact: false });
  await scan.click();
  const added = async () => want.test((await bar.count()) ? ((await bar.textContent()) ?? '') : '');
  // Wait for the tap's outcome: the bar reaches `want`, or the app says nothing was in view.
  await expect.poll(async () => (await added()) || (await nothing.isVisible())).toBe(true);
  if (!(await added())) await scan.click();
  await expect(bar).toHaveText(want);
}

test.describe('Slice scan - mobile POS camera scan', { tag: ['@slice-scan', '@retailer', '@pos'] }, () => {
  test('SC1 camera scan adds the product to the bill; tap Scan adds it again; bill saves and stock drops', async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    await retailerLogin(page, SFB_RETAILER.username);
    await page.goto('/dashboard/pos');
    await expect(page.getByText(SFB_PRODUCT.RICE.name).first()).toBeVisible();

    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    // Tap Scan with the code in view, like a counter scanner's trigger: each tap adds one.
    // (The first code is meant to be read without a tap; that is SC2, fixme.)
    const bar = page.getByRole('button', { name: /^\d+ items? ₹/ });
    await scanOnce(page, bar, null, /1 item\s*₹100/);
    await page.getByRole('button', { name: 'Close scanner' }).click();
    await expect(bar).toHaveText(/1 item\s*₹100/);
    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    await scanOnce(page, bar, /1 item\s*₹100/, /1 item\s*₹200/);
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

  // BUG OE-386: BarcodeScanner sets firstCodeTaken before it checks `closing`, so a scanner that is shutting
  // down (StrictMode's first mount in next dev, or Switch camera) swallows the first code.
  fixme('SC2 first code in view is added without a tap @slice-scan', async ({ page }) => {
    test.info().annotations.push({ type: 'bug', description: 'https://vin8003.atlassian.net/browse/OE-386 first code swallowed by a closing scanner' });
    await retailerLogin(page, SFB_RETAILER.username);
    await page.goto('/dashboard/pos');
    await expect(page.getByText(SFB_PRODUCT.RICE.name).first()).toBeVisible();
    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    await expect(page.getByText(`Added ${SFB_PRODUCT.RICE.name}`).first()).toBeVisible();
    await page.getByRole('button', { name: 'Close scanner' }).click();
    await expect(page.getByRole('button', { name: /^\d+ items? ₹/ })).toHaveText(/1 item\s*₹100/);
  });
});
