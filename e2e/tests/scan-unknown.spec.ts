/**
 * Slice scan: a camera scan of a barcode the shop does not stock (fake camera plays SFB.unknown_barcode).
 * Own file: the fake camera clip is a browser launch option, so it cannot change per describe.
 */
import { join } from 'node:path';
import { devices } from '@playwright/test';
import { test, expect } from '../fixtures';
import { retailerLogin } from '../helpers';
import { SFB, SFB_PRODUCT, SFB_RETAILER, writeBarcodeY4m } from '../sfb';

const CLIP = writeBarcodeY4m(SFB.unknown_barcode, join(__dirname, '..', '.fake-camera', 'sfb-unknown.y4m'));

test.use({
  ...devices['Pixel 7'],
  defaultBrowserType: 'chromium',
  launchOptions: {
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${CLIP}`],
  },
  permissions: ['camera'],
});

test.describe('Slice scan - camera scan of an unknown barcode', { tag: ['@slice-scan', '@retailer', '@pos'] }, () => {
  test('SC3 unknown barcode closes the camera, offers Quick Add for that code and leaves the bill empty', async ({ page }) => {
    await retailerLogin(page, SFB_RETAILER.username);
    await page.goto('/dashboard/pos');
    await expect(page.getByText(SFB_PRODUCT.RICE.name).first()).toBeVisible();
    await page.getByRole('button', { name: 'Scan barcode with camera' }).click();
    const quickAdd = page.getByTestId('pos-unknown-barcode');
    const scan = page.getByRole('button', { name: 'Scan', exact: true });
    // One tap per frame read; stop as soon as Quick Add opens (it closes the camera).
    for (let tap = 0; tap < 5 && !(await quickAdd.isVisible()); tap++) {
      if (await scan.isVisible()) await scan.click();
      await quickAdd.waitFor({ timeout: 4000 }).catch(() => undefined);
    }
    await expect(quickAdd).toHaveText('Unknown Barcode');
    await expect(page.getByText(`[${SFB.unknown_barcode}]`)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Close scanner' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^\d+ items? ₹/ })).toHaveCount(0);
    await expect(page.getByTestId('pos-cart-line')).toHaveCount(0);
  });
});
