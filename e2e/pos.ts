import { type Page } from '@playwright/test';
import { expect, urls } from './fixtures';
import { rupees } from './helpers';

export const BARCODE = {
  P1: '8900000000011',
  P2: '8900000000028',
  P3: '8900000000035',
  P4: '8900000000042',
  P5: '8900000000059',
  UNKNOWN: '8900000000999',
};

export async function openPos(page: Page) {
  await page.goto(`${urls.retailer}/dashboard/pos`);
  // Products are loaded once the seeded items render in the grid.
  await expect(page.getByText('Atta 5kg').first()).toBeVisible();
}

export async function scan(page: Page, barcode: string) {
  const search = page.getByTestId('pos-search');
  await search.fill(barcode);
  await search.press('Enter');
}

export function cartLine(page: Page, barcode: string) {
  return page.locator(`[data-testid="pos-cart-line"][data-barcode="${barcode}"]`);
}

export async function expectLineQty(page: Page, barcode: string, qty: number) {
  await expect(cartLine(page, barcode).getByTestId('pos-cart-line-qty')).toHaveValue(String(qty));
}

export async function posTotal(page: Page) {
  return rupees(await page.getByTestId('pos-total').textContent());
}

/** Common cart for A1-A3: P1 x1, P2 x2, P4 x3 = 620. Asserts each rescan increments the same line. */
export async function scanCommonCart(page: Page) {
  await scan(page, BARCODE.P1);
  await expectLineQty(page, BARCODE.P1, 1);
  await scan(page, BARCODE.P2);
  await expectLineQty(page, BARCODE.P2, 1);
  await scan(page, BARCODE.P2);
  await expectLineQty(page, BARCODE.P2, 2);
  for (const qty of [1, 2, 3]) {
    await scan(page, BARCODE.P4);
    await expectLineQty(page, BARCODE.P4, qty);
  }
  await expect(page.getByTestId('pos-cart-line')).toHaveCount(3);
  await expect(page.getByTestId('pos-total')).toHaveText('₹620');
}

export async function attachCustomer(page: Page, mobile10: string) {
  const mobile = page.getByTestId('pos-customer-mobile');
  await mobile.fill(mobile10);
  const verified = page.waitForResponse((r) => r.url().includes('/erp/verify-pos-customer/'));
  await mobile.blur();
  await verified;
}
