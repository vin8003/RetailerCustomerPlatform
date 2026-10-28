/**
 * F1–F9 from CASES.md §4 (+ F9 from review). Each asserts the CORRECT value.
 * F2, F3, F4, F6, F8 are fixed on main and run as normal regression tests.
 * F1, F5, F7, F9 are still open: test.fixme with a bug annotation linking the Jira ticket.
 * E2E_RUN_FIXME=1 runs the fixme ones anyway (to confirm a bug is still there, or is gone).
 */
import { test, expect, urls } from '../fixtures';
import {
  addToCart, authed, createOffer, customerCart, customerLogin, customerToken, customerUseSeedCity,
  djangoShell, getJson, placeCodOrder, retailerLogin,
} from '../helpers';
import { C2_MOBILE as C2_PHONE, PRODUCT, R1 } from '../seed';

const JIRA = 'https://vin8003.atlassian.net/browse/';
const known = (ticket: string, bug: string) => ({ annotation: { type: 'bug', description: `${JIRA}${ticket} ${bug}` } });
const fixme = process.env.E2E_RUN_FIXME ? test : test.fixme;

fixme('F1 flat offer is taken once per line, not per unit @F1 @customer @offers',
  known('OE-370', 'O1 flat ₹20 on the P5 line is applied per unit: P5×3 gives ₹240.00, expected ₹280.00'),
  async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'O1 ₹20 off ghee', offer_type: 'flat_amount', value_type: 'amount', value: '20.00' }, seed.products.P5);
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P5, 3);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(300);
    expect(cart.discounted_total).toBe(280);
  });

test('F2 percentage cap applies to the price, not just the label @F2 @customer @offers',
  async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'O2 10% capped', offer_type: 'cart_value', value_type: 'percent', value: '10.00', max_discount_amount: '50.00' });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 3);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(750);
    expect(cart.discounted_total).toBe(700);
  });

test('F3 stackable cart offer also covers already-discounted items @F3 @customer @offers',
  async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await createOffer(api, r1, { name: 'O3 ₹10 off ghee', offer_type: 'flat_amount', value_type: 'amount', value: '10.00', is_stackable: true }, seed.products.P5);
    await createOffer(api, r1, { name: 'O4 5% stackable', offer_type: 'cart_value', value_type: 'percent', value: '5.00', is_stackable: true });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P5, 2);
    await addToCart(api, token, seed.products.P2, 1);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.discounted_total).toBe(304);
  });

test('F4 only the applied non-stackable offer counts toward savings @F4 @customer @offers',
  async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await createOffer(api, r1, { name: 'F4 10% cart', offer_type: 'cart_value', value_type: 'percent', value: '10.00', priority: 2 });
    await createOffer(api, r1, { name: 'F4 5% cart', offer_type: 'cart_value', value_type: 'percent', value: '5.00', priority: 1 });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 2); // ₹500
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_offers).toHaveLength(1);
    const applied = cart.applied_offers.reduce((sum: number, o: { savings: number }) => sum + o.savings, 0);
    expect(cart.total_savings).toBe(applied);
    expect(cart.discounted_total).toBe(cart.subtotal - cart.total_savings);
  });

fixme('F5 duplicate product name is a 4xx with a message, not a 500 @F5 @retailer @products',
  known('OE-371', `Creating a second "${PRODUCT.P1.name}" at R1 returns 500`),
  async ({ api, retailerToken }) => {
    const r1 = await retailerToken();
    const response = await api.post('products/create/', {
      ...authed(r1),
      data: { name: PRODUCT.P1.name, price: PRODUCT.P1.price, quantity: 10, unit: 'piece' },
    });
    expect(response.status()).toBeGreaterThanOrEqual(400);
    expect(response.status()).toBeLessThan(500);
    expect(JSON.stringify(await response.json())).toMatch(/already|exists|duplicate/i);
    const list = await api.get(`products/?search=${encodeURIComponent(PRODUCT.P1.name)}`, authed(r1));
    expect(JSON.stringify(await list.json()).split(JSON.stringify(PRODUCT.P1.name)).length - 1).toBe(1);
  });

test('F6 an order and a khata entry made at 00:30 IST are dated that IST day (29 Oct) @F6 @customer @retailer @khata @orders', async ({ page, context, api, seed, retailerToken }) => {
  // The server cannot be clock-pinned, so restamp both rows at 28 Oct 2026 19:00 UTC = 29 Oct 2026 00:30 IST.
  const STAMP = 'datetime(2026, 10, 28, 19, 0, tzinfo=timezone.utc)';
  const token = await customerToken(api, C2_PHONE);
  await addToCart(api, token, seed.products.P4, 1);
  const order = await placeCodOrder(api, token, seed.retailers.R1, seed.c2_address);
  const r1 = await retailerToken();
  const paid = await api.post('customer/retailer/payment/record/', {
    ...authed(r1),
    data: { customer_id: seed.customers.C1, amount: 50, payment_mode: 'cash' },
  });
  expect(paid.status(), await paid.text()).toBeLessThan(300);
  djangoShell(
    'from datetime import datetime, timezone\nfrom orders.models import Order\nfrom retailers.models import CustomerLedger\n'
    + `Order.objects.filter(id=${order.id}).update(created_at=${STAMP})\n`
    + `CustomerLedger.objects.filter(customer_id=${seed.customers.C1}, retailer__user__username='${R1.username}').update(created_at=${STAMP})\n`,
  );

  const body = JSON.stringify(await (await api.get(`orders/${order.id}/`, authed(token))).json());
  expect(body).not.toMatch(/"(order_date|date)":\s*"2026-10-28/);
  const ledger = await getJson(api, `customer/retailer/ledger/${seed.customers.C1}/`, r1);
  expect(ledger.results).toHaveLength(1);
  expect(istDate(ledger.results[0].created_at)).toBe('2026-10-29');

  await customerUseSeedCity(page);
  await customerLogin(page, C2_PHONE);
  await page.goto(`${urls.customer}/orders/detail?id=${order.id}`);
  await expect(page.getByText('29 Oct 2026').first()).toBeVisible();
  const retailer = await context.newPage();
  await retailerLogin(retailer);
  await retailer.goto(`${urls.retailer}/dashboard/orders/details?id=${order.id}`);
  await expect(retailer.getByText(/29 Oct|Oct 29/).first()).toBeVisible();
  await retailer.goto(`${urls.retailer}/dashboard/customers/details?id=${seed.customers.C1}`);
  await expect(retailer.getByText(/29 Oct|Oct 29/).first()).toBeVisible();
});

/** YYYY-MM-DD of an API timestamp, read in IST. */
function istDate(iso: string) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date(iso));
}

fixme('F7 WAITING_FOR_CUSTOMER_APPROVAL has a human label in My Orders @F7 @customer @orders',
  known('OE-372', 'My Orders shows the raw "waiting for customer approval" enum'),
  async ({ page, api, seed }) => {
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P4, 1);
    const order = await placeCodOrder(api, token, seed.retailers.R1, seed.c2_address);
    djangoShell(`from orders.models import Order\nOrder.objects.filter(id=${order.id}).update(status='waiting_for_customer_approval')\n`);

    await customerUseSeedCity(page);
    await customerLogin(page, C2_PHONE);
    await page.goto(`${urls.customer}/orders`);
    const status = page.locator(`[data-testid="order-card"][data-order-id="${order.id}"]`).getByTestId('order-card-status');
    await expect(status).toHaveText(/^needs your approval$/i);
  });

test('F8 offer and coupon discounts each show once in the cart @F8 @customer @offers',
  async ({ page, api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await createOffer(api, r1, { name: 'F8 ₹20 off ghee', offer_type: 'flat_amount', value_type: 'amount', value: '20.00', is_stackable: true }, seed.products.P5);
    await createOffer(api, r1, { name: 'F8 coupon', offer_type: 'cart_value', value_type: 'amount', value: '30.00', coupon_code: 'E2E30', is_public: false, is_stackable: true });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P5, 1);
    await addToCart(api, token, seed.products.P1, 1);
    const apply = await api.post('cart/apply-coupon/', { ...authed(token), data: { retailer_id: seed.retailers.R1, coupon_code: 'E2E30' } });
    expect(apply.status(), await apply.text()).toBe(200);

    await customerUseSeedCity(page);
    await customerLogin(page, C2_PHONE);
    await page.evaluate((id) => localStorage.setItem('current_retailer_id', String(id)), seed.retailers.R1);
    await page.goto(`${urls.customer}/cart`);
    await expect(page.getByText('-₹30.00', { exact: true })).toHaveCount(1);
    await expect(page.getByText('-₹50.00', { exact: true })).toHaveCount(1); // total savings = 20 + 30, once
  });

fixme('F9 Packed straight from Confirmed (offered by the UI) is accepted, not a 400 @F9 @retailer @orders',
  known('OE-373', 'The retailer UI offers Confirmed → Packed but the API rejects it with 400; B3 goes via Processing'),
  async ({ page, api, seed }) => {
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P4, 1);
    const order = await placeCodOrder(api, token, seed.retailers.R1, seed.c2_address);

    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/orders/details?id=${order.id}`);
    await page.getByTestId('order-status-next-confirmed').click();
    await page.getByTestId('order-confirm-submit').click();
    await expect(page.getByTestId('order-status')).toHaveText('CONFIRMED');
    await page.getByTestId('order-status-next-packed').click();
    await expect(page.getByTestId('order-status')).toHaveText('PACKED');
  });
