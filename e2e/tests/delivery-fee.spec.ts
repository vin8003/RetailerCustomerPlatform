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

/** The server's quote for a saved SFB address (the same call checkout makes). */
async function quote(api: Parameters<typeof getJson>[0], token: string, ids: SfbIds, address: AddressKey, orderTotal: string) {
  return getJson(api, `retailers/${ids.retailer}/delivery-quote/?address_id=${ids.addresses[address]}&order_total=${orderTotal}`, token);
}

test.describe('Slice fee - delivery-quote bands and radius (API)', { tag: ['@slice-fee', '@customer'] }, () => {
  // Band edges: 2 km and 5 km are the last km of their band; 6 km is one started km past 5; 8 km is the radius.
  for (const key of ['NEAR', 'AT2', 'MID', 'AT5', 'AT6', 'FAR', 'AT8'] as const) {
    test(`DQ ${key}: ${SFB_ADDRESS[key].km} km is quoted ₹${SFB_ADDRESS[key].fee}`, async ({ api, seed }) => {
      const ids = sfbIds(seed);
      const token = await customerToken(api, SFB_CUSTOMER_MOBILE);
      expect(await quote(api, token, ids, key, '100.00')).toMatchObject({
        deliverable: true, distance_km: SFB_ADDRESS[key].km, delivery_fee: SFB_ADDRESS[key].fee, free_delivery_applied: false,
      });
    });
  }

  for (const key of ['PAST8', 'OUT'] as const) {
    test(`DQ ${key}: ${SFB_ADDRESS[key].km} km is outside the 8 km radius`, async ({ api, seed }) => {
      const ids = sfbIds(seed);
      const token = await customerToken(api, SFB_CUSTOMER_MOBILE);
      expect(await quote(api, token, ids, key, '100.00')).toMatchObject({
        deliverable: false, distance_km: SFB_ADDRESS[key].km,
        reason: `This address is ${SFB_ADDRESS[key].km} km away; the shop delivers within 8 km.`,
      });
    });
  }

  test('DQ FREE: ₹500 at 3.5 km is free, ₹499.99 still pays ₹40', async ({ api, seed }) => {
    const ids = sfbIds(seed);
    const token = await customerToken(api, SFB_CUSTOMER_MOBILE);
    expect(await quote(api, token, ids, 'MID', '500.00'))
      .toMatchObject({ deliverable: true, delivery_fee: '0.00', fee_before_free_delivery: '40.00', free_delivery_applied: true });
    expect(await quote(api, token, ids, 'MID', '499.99'))
      .toMatchObject({ deliverable: true, delivery_fee: '40.00', free_delivery_applied: false });
  });
});

test.describe('Slice fee - distance delivery fee at checkout', { tag: ['@slice-fee', '@customer'] }, () => {
  test(`DF NEAR: ${SFB_ADDRESS.NEAR.km} km shows ₹${SFB_ADDRESS.NEAR.fee} delivery and can be ordered`, async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    await openCheckout(page, api, ids, 1, 'NEAR');
    await expect(page.getByTestId('checkout-delivery-fee')).toHaveText(`₹${SFB_ADDRESS.NEAR.fee}`);
    await expect(page.getByTestId('checkout-total')).toHaveText('₹120.00');
    await expect(page.getByTestId('checkout-place-order')).toBeEnabled();
  });

  test(`DF OUT: ${SFB_ADDRESS.OUT.km} km is outside the 8 km radius and cannot be ordered`, async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    await openCheckout(page, api, ids, 1, 'OUT');
    // delivery_pricing.quote_delivery's reason, shown as is.
    await expect(page.getByTestId('checkout-delivery-unavailable'))
      .toHaveText(`This address is ${SFB_ADDRESS.OUT.km} km away; the shop delivers within 8 km.`);
    await expect(page.getByTestId('checkout-delivery-fee')).toHaveCount(0);
    await expect(page.getByTestId('checkout-place-order')).toBeDisabled();
    await expect(page.getByTestId('checkout-place-order')).toHaveText('Outside delivery area');
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
