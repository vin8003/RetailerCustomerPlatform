/**
 * Slice fee: distance-based delivery fee at customer checkout.
 * SFB Mart charges ₹20 up to 2 km, ₹40 up to 5 km, then ₹10 per started km past 5 km, delivers within 8 km,
 * and delivers free from ₹500. The SFB customer has one address in each band (seed/scan_fee_bundles.json).
 */
import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { addToCart, customerLogin, customerToken, customerUseSeedCity, getJson } from '../helpers';
import { SFB_ADDRESS, SFB_CUSTOMER_MOBILE, sfbIds, type SfbIds } from '../sfb';

type AddressKey = keyof typeof SFB_ADDRESS;

/** Put RICE x qty in the cart (API), open checkout in the browser, pick a slot and the address. */
async function openCheckout(page: Page, api: Parameters<typeof addToCart>[0], ids: SfbIds, qty: number, address: AddressKey,
  product: 'RICE' | 'GHEE' = 'RICE') {
  const token = await customerToken(api, SFB_CUSTOMER_MOBILE);
  await addToCart(api, token, ids.products[product], qty);
  await customerUseSeedCity(page);
  await customerLogin(page, SFB_CUSTOMER_MOBILE);
  // The cart page shows the current store's cart (what opening the store would remember).
  await page.addInitScript((id) => localStorage.setItem('current_retailer_id', id), String(ids.retailer));
  await page.goto(`${urls.customer}/cart`);
  await page.getByTestId('cart-checkout').click();
  await page.waitForURL('**/checkout**');
  await page.getByTestId('slot-picker-open').click();
  // Any offered slot will do; the fee does not depend on it (SL1 is not on the default day tab before 10:00 IST).
  await page.getByTestId('slot-option').first().click();
  await page.getByTestId('slot-confirm').click();
  // NEAR is the default address; the fee assertions wait for the server quote of the picked one.
  await page.getByTestId(`checkout-address-${ids.addresses[address]}`).click();
  await page.getByTestId('checkout-pay-cod').click();
  return token;
}

test.describe('Slice fee - distance delivery fee at checkout', { tag: ['@slice-fee', '@customer'] }, () => {
  for (const [key, total] of [
    ['NEAR', '₹120.00'], ['MID', '₹140.00'], ['FAR', '₹160.00'],
    // Band edges: 2 km and 5 km are the last km of their band; 6 km is one started km past 5; 8 km is the radius.
    ['AT2', '₹120.00'], ['AT5', '₹140.00'], ['AT6', '₹150.00'], ['AT8', '₹170.00'],
  ] as const) {
    test(`DF ${key}: ${SFB_ADDRESS[key].km} km pays ₹${SFB_ADDRESS[key].fee} delivery`, async ({ page, api, seed }) => {
      const ids = sfbIds(seed);
      await openCheckout(page, api, ids, 1, key);
      await expect(page.getByTestId('checkout-delivery-fee')).toHaveText(`₹${SFB_ADDRESS[key].fee}`);
      await expect(page.getByTestId('checkout-total')).toHaveText(total);
      await expect(page.getByTestId('checkout-place-order')).toBeEnabled();
    });
  }

  for (const key of ['OUT', 'PAST8'] as const) {
    test(`DF ${key}: ${SFB_ADDRESS[key].km} km is outside the 8 km radius and cannot be ordered`, async ({ page, api, seed }) => {
      const ids = sfbIds(seed);
      await openCheckout(page, api, ids, 1, key);
      // delivery_pricing.quote_delivery's reason, shown as is.
      await expect(page.getByTestId('checkout-delivery-unavailable'))
        .toHaveText(`This address is ${SFB_ADDRESS[key].km} km away; the shop delivers within 8 km.`);
      await expect(page.getByTestId('checkout-delivery-fee')).toHaveCount(0);
      await expect(page.getByTestId('checkout-place-order')).toBeDisabled();
      await expect(page.getByTestId('checkout-place-order')).toHaveText('Outside delivery area');
    });
  }

  test('DF FREE: ₹500 cart at 3.5 km delivers free', async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    await openCheckout(page, api, ids, 5, 'MID');
    await expect(page.getByTestId('checkout-total')).toHaveText('₹500.00');
    await expect(page.getByTestId('checkout-delivery-fee')).toHaveCount(0);
  });

  test('DF NOT FREE: ₹499.99 cart at 3.5 km still pays ₹40', async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    await openCheckout(page, api, ids, 1, 'MID', 'GHEE');
    await expect(page.getByTestId('checkout-delivery-fee')).toHaveText('₹40.00');
    await expect(page.getByTestId('checkout-total')).toHaveText('₹539.99');
  });

  test('DF ORDER: placed order at 6.5 km saves the ₹60 fee and ₹160 total', async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    const token = await openCheckout(page, api, ids, 1, 'FAR');
    await expect(page.getByTestId('checkout-total')).toHaveText('₹160.00');
    const placed = page.waitForResponse((r) => r.url().includes('/orders/place/') && r.request().method() === 'POST');
    await page.getByTestId('checkout-place-order').click();
    const response = await placed;
    expect(response.status(), await response.text()).toBe(201);
    await page.waitForURL('**/orders/detail?id=*');
    const orderId = Number(new URL(page.url()).searchParams.get('id'));
    const order = await getJson(api, `orders/${orderId}/`, token);
    expect(Number(order.delivery_fee)).toBe(60);
    expect(Number(order.total_amount)).toBe(160);
    expect(order.items.map((i: { product: number; quantity: number }) => [i.product, Number(i.quantity)]))
      .toEqual([[ids.products.RICE, 1]]);
  });
});
