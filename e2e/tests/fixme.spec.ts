/**
 * F1–F8: known product bugs (CASES.md §4). Each asserts the CORRECT value and is marked
 * test.fixme with a bug annotation, so the suite stays green until the fix lands.
 * When a bug is fixed, drop the fixme and the test becomes a regression guard.
 * E2E_RUN_FIXME=1 runs them anyway (to confirm a bug is still there, or is gone).
 */
import { test, expect, urls } from '../fixtures';
import {
  addToCart, authed, createOffer, customerCart, customerLogin, customerToken, customerUseSeedCity,
  djangoShell, placeCodOrder, retailerLogin,
} from '../helpers';

const C2_PHONE = '9000000002';
const known = (bug: string) => ({ annotation: { type: 'bug', description: bug } });
const fixme = process.env.E2E_RUN_FIXME ? test : test.fixme;

fixme('F1 flat offer is taken once per line, not per unit @F1',
  known('O1 flat ₹20 on the P5 line is applied per unit: P5×3 gives ₹240.00, expected ₹280.00'),
  async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'O1 ₹20 off ghee', offer_type: 'flat_amount', value_type: 'amount', value: '20.00' }, seed.products.P5);
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P5, 3);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(300);
    expect(cart.discounted_total).toBe(280);
  });

fixme('F2 percentage cap applies to the price, not just the label @F2',
  known('O2 10% off cart capped at ₹50: P1×3 gives ₹675.00, expected ₹700.00'),
  async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'O2 10% capped', offer_type: 'cart_value', value_type: 'percent', value: '10.00', max_discount_amount: '50.00' });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 3);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(750);
    expect(cart.discounted_total).toBe(700);
  });

fixme('F3 stackable cart offer also covers already-discounted items @F3',
  known('O4 stackable 5% skips P5 (discounted by O3): total ₹313.00, expected ₹304.00'),
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

fixme('F4 only the applied non-stackable offer counts toward savings @F4',
  known('Two eligible non-stackable cart offers: savings include the one that did not apply'),
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

fixme('F5 duplicate product name is a 4xx with a message, not a 500 @F5',
  known('Creating a second "Atta 5kg" at R1 returns 500'),
  async ({ api, retailerToken }) => {
    const r1 = await retailerToken();
    const response = await api.post('products/create/', {
      ...authed(r1),
      data: { name: 'Atta 5kg', price: '250.00', quantity: 10, unit: 'piece' },
    });
    expect(response.status()).toBeGreaterThanOrEqual(400);
    expect(response.status()).toBeLessThan(500);
    expect(JSON.stringify(await response.json())).toMatch(/already|exists|duplicate/i);
    const list = await api.get('products/?search=Atta', authed(r1));
    expect(JSON.stringify(await list.json()).match(/"Atta 5kg"/g)).toHaveLength(1);
  });

fixme('F6 an order placed at 23:30 IST is dated that IST day on both apps @F6',
  known('Server-stamped order/ledger dates are UTC dates: 23:30 IST shows the next or previous day'),
  async ({ page, context, api, seed }) => {
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P4, 1);
    const order = await placeCodOrder(api, token, seed.retailers.R1, seed.c2_address);
    // The server cannot be clock-pinned, so stamp the order as placed at 28 Oct 2026 23:30 IST.
    djangoShell(`from orders.models import Order\nfrom datetime import datetime, timezone\nOrder.objects.filter(id=${order.id}).update(created_at=datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc))\n`);
    const detail = await api.get(`orders/${order.id}/`, authed(token));
    const body = JSON.stringify(await detail.json());
    expect(body).not.toMatch(/"(order_date|date)":\s*"2026-10-29/);

    await customerUseSeedCity(page);
    await customerLogin(page, C2_PHONE);
    await page.goto(`${urls.customer}/orders/detail?id=${order.id}`);
    await expect(page.getByText('28 Oct 2026').first()).toBeVisible();
    const retailer = await context.newPage();
    await retailerLogin(retailer);
    await retailer.goto(`${urls.retailer}/dashboard/orders/details?id=${order.id}`);
    await expect(retailer.getByText(/28 Oct|Oct 28/).first()).toBeVisible();
  });

fixme('F7 WAITING_FOR_CUSTOMER_APPROVAL has a human label in My Orders @F7',
  known('My Orders shows the raw "waiting for customer approval" enum'),
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

fixme('F8 offer and coupon discounts each show once in the cart @F8',
  known('Cart lists the coupon discount twice and the savings line double-counts it'),
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
