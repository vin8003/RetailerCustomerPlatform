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

const CLIP = writeBarcodeY4m(SFB_PRODUCT.RICE.barcode, join(__dirname, '..', '.fake-camera', 'sfb-rice.y4m'));

test.use({
  ...devices['Pixel 7'],
  defaultBrowserType: 'chromium',
  launchOptions: {
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${CLIP}`],
  },
  permissions: ['camera'],
});

const scanButton = (page: Page) => page.getByRole('button', { name: 'Scan', exact: true });
/** The bill total on the cart bar ("1 item ₹200" -> 200); 0 while the bill is empty. */
async function billTotal(bar: Locator) {
  if (!(await bar.count())) return 0;
  return Number(/₹([\d.]+)/.exec((await bar.textContent()) ?? '')?.[1]);
}

/**
 * Tap Scan until a tap is accepted (the bill changes). A tap with no code yet in view adds nothing
 * ("No barcode in view"), so it is safe to tap again. Once a tap is accepted the scanner has handled its
 * first code in view (auto-read, or swallowed by OE-386), so from then on only taps add codes.
 */
async function primeScanner(page: Page, bar: Locator) {
  for (let tap = 1; tap <= 10; tap++) {
    const before = await billTotal(bar);
    await scanButton(page).click();
    const changed = await expect.poll(() => billTotal(bar), { timeout: 1000 }).not.toBe(before).then(() => true, () => false);
    if (changed) return;
  }
  throw new Error('Scan never read the barcode in view');
}

test.describe('Slice scan - mobile POS camera scan', { tag: ['@slice-scan', '@retailer', '@pos'] }, () => {
  test('SC1 with the scanner reading, each tap of Scan adds one; the bill saves and stock drops', async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    await retailerLogin(page, SFB_RETAILER.username);
    await page.goto('/dashboard/pos');
    await expect(page.getByText(SFB_PRODUCT.RICE.name).first()).toBeVisible();

    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    // Tap Scan with the code in view, like a counter scanner's trigger. Whether the first code is read
    // without a tap is SC2's job (OE-386), so SC1 counts only what the taps add after the scanner is reading.
    const bar = page.getByRole('button', { name: /^\d+ items? ₹/ });
    await primeScanner(page, bar);
    const primed = await billTotal(bar);
    await scanButton(page).click();
    await expect(bar).toHaveText(new RegExp(`1 item\\s*₹${primed + 100}(?!\\d)`));
    await page.getByRole('button', { name: 'Close scanner' }).click();
    // Same product each time: one line.
    const total = primed + 100;
    const quantity = total / Number(SFB_PRODUCT.RICE.price);
    await expect(bar).toHaveText(new RegExp(`1 item\\s*₹${total}(?!\\d)`));

    await bar.click();
    await expect(page.getByTestId('pos-total')).toHaveText(`₹${total}`);
    await page.getByTestId('pos-pay-cash').click();
    const checkout = posCheckoutResponse(page);
    // Phone layout: the sticky bottom button (pos-complete-bill is the desktop one, hidden here).
    await page.getByRole('button', { name: 'COMPLETE BILL', exact: true }).click();
    const response = await checkout;
    expect(response.status(), await response.text()).toBe(201);
    const { order } = await response.json();
    await expect(page.getByTestId('pos-paid-total')).toHaveText(`₹${total}`);

    const token = await sfbRetailerToken(api, PASSWORD);
    const saved = await getJson(api, `orders/${order.id}/`, token);
    expect(Number(saved.total_amount)).toBe(total);
    expect(saved.items.map((i: { product: number; quantity: number }) => [i.product, Number(i.quantity)]))
      .toEqual([[ids.products.RICE, quantity]]);
    expect(await stock(api, token, ids.products.RICE)).toBe(Number(SFB_PRODUCT.RICE.stock) - quantity);
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
