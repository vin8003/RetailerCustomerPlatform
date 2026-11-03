/**
 * Order gates (COVERAGE.md: out-of-stock at checkout, invalid transitions, cancel at delivered).
 * O1 is in the always-run @smoke subset: the COD checkout must refuse an order the shop can no longer fill.
 */
import { test, expect, urls } from '../fixtures';
import { authed, customerLogin, customerToken, customerUseSeedCity, djangoShell, getJson, productStock, sl1 } from '../helpers';
import { advance, placeOrder } from '../edge';
import { C2_MOBILE, R1 } from '../seed';

/** Orders C2 has at R1 (the pair O1 checks out with). */
const orderCount = (customerId: number, retailerId: number) =>
  Number(djangoShell(
    `from orders.models import Order\nprint(Order.objects.filter(customer_id=${customerId}, retailer_id=${retailerId}).count())\n`,
  ).trim().split('\n').pop());

test('O1 stock sold out while on the COD checkout page: place order refused, no order, stock untouched @smoke @customer @orders', async ({ page, api, seed, retailerToken }) => {
  const P3 = seed.products.P3;
  const rt = await retailerToken();
  const before = await orderCount(seed.customers.C2, seed.retailers.R1);

  await customerUseSeedCity(page);
  await customerLogin(page, C2_MOBILE);
  // The cart page needs a selected store; open R1's storefront first and add P3 x2 the way B1 does.
  await page.goto(`${urls.customer}/retailers`);
  await page.getByText(R1.shop_name).first().click();
  await page.waitForURL('**/retailer?id=*');
  await page.getByTestId(`add-to-cart-${P3}`).first().click();
  await page.getByTestId(`cart-increment-${P3}`).first().click();
  await expect(page.getByTestId(`cart-qty-${P3}`).first()).toHaveText('2');
  await page.goto(`${urls.customer}/cart`);
  await page.getByTestId('cart-checkout').click();
  await page.waitForURL('**/checkout**');
  await page.getByTestId('slot-picker-open').click();
  await page.getByTestId(`slot-day-${sl1().start.slice(0, 10)}`).click();
  await page.locator(`[data-testid="slot-option"][data-slot-start="${sl1().start}"]`).click();
  await page.getByTestId('slot-confirm').click();
  await page.getByTestId(`checkout-address-${seed.c2_address}`).click();
  await page.getByTestId('checkout-pay-cod').click();
  // Someone else bought it while the customer was on the checkout page: only 1 left.
  djangoShell(`from products.models import Product\nProduct.objects.filter(id=${P3}).update(quantity=1)\n`);

  const placed = page.waitForResponse((r) => r.url().includes('/orders/place/') && r.request().method() === 'POST');
  await page.getByTestId('checkout-place-order').click();
  const response = await placed;
  expect(response.status(), await response.text()).toBe(400);
  // OrderCreateSerializer.validate: saleable stock check.
  expect(await response.json()).toMatchObject({
    non_field_errors: [expect.stringMatching(/^Total combined cart items require 2(\.0+)? of 'Sunflower Oil 1L', but only 1(\.0+)? is available\.$/)],
  });
  await expect(page).toHaveURL(/\/checkout/);

  expect(await orderCount(seed.customers.C2, seed.retailers.R1)).toBe(before);
  expect(await productStock(api, rt, P3)).toBe(1);
});

test.describe('Order gates - status rules', { tag: ['@orders', '@retailer'] }, () => {
  test('O2 skipped or backward status changes are refused and leave the order as it was', async ({ api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const rt = await retailerToken();
    for (const status of ['packed', 'out_for_delivery', 'delivered']) {
      const r = await api.patch(`orders/${order.id}/status/`, { ...authed(rt), data: { status } });
      expect(r.status(), `pending → ${status}`).toBe(400);
      // OrderStatusUpdateSerializer.validate_status → ensure_transition_allowed (orders/domain/status_policy.py).
      expect(await r.json()).toMatchObject({ status: [`Cannot change status from 'pending' to '${status}'`] });
    }
    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('pending');

    await advance(api, rt, order.id, ['confirmed', 'packed', 'delivered']);
    const back = await api.patch(`orders/${order.id}/status/`, { ...authed(rt), data: { status: 'pending' } });
    expect(back.status(), 'delivered → pending').toBe(400);
    expect(await back.json()).toMatchObject({ status: ["Cannot change status from 'delivered' to 'pending'"] });
    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('delivered');
  });

  test('O3 a delivered order cannot be cancelled by the customer @customer', async ({ api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const rt = await retailerToken();
    await advance(api, rt, order.id, ['confirmed', 'packed', 'delivered']);
    const cancel = await api.post(`orders/${order.id}/cancel/`, { ...authed(ct), data: {} });
    expect(cancel.status()).toBe(400);
    // cancel_order: Order.can_be_cancelled is only pending/confirmed/processing.
    expect(await cancel.json()).toMatchObject({ error: 'Order cannot be cancelled' });
    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('delivered');
  });
});
