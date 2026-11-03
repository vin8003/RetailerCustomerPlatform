import { type Page } from '@playwright/test';
import { expect, urls } from './fixtures';
import { rupees } from './helpers';
import { PRODUCT } from './seed';

export const BARCODE = {
  P1: PRODUCT.P1.barcode,
  P2: PRODUCT.P2.barcode,
  P3: PRODUCT.P3.barcode,
  P4: PRODUCT.P4.barcode,
  P5: PRODUCT.P5.barcode,
  UNKNOWN: '8900000000999',
};

export async function openPos(page: Page) {
  await page.goto(`${urls.retailer}/dashboard/pos`);
  // Products are loaded once the seeded items render in the grid.
  await expect(page.getByText(PRODUCT.P1.name).first()).toBeVisible();
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
  // fill() sets the value in one step, so even if the POS's 50 ms refocus to the scan box blurs the
  // field early, the verify call still carries the full number. Wait on that call, not on focus.
  // verify-pos-customer is a GET (?mobile_number=), so the number is matched in the URL.
  const mobile = page.getByTestId('pos-customer-mobile');
  const req = page.waitForRequest(
    (r) => r.url().includes('/erp/verify-pos-customer/') && r.url().includes(`mobile_number=${mobile10}`),
  );
  await mobile.fill(mobile10);
  await mobile.blur();
  const verified = await (await req).response();
  expect(verified?.ok(), 'verify-pos-customer ok').toBe(true);
  await expect(mobile).toHaveValue(mobile10);
}
