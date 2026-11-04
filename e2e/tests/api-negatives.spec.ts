/**
 * API negatives (COVERAGE.md "API negatives"): each test checks the exact error body from the backend
 * and re-reads state to prove nothing changed. Seeded data only.
 */
import { test, expect } from '../fixtures';
import { authed, customerCart, customerToken, djangoShell, getJson, productStock } from '../helpers';
import { advance, fixme, known, placeOrder, posBill, price, tryPlaceOrder } from '../edge';
import { C1_MOBILE, C2_MOBILE, R2 } from '../seed';

const setStock = (productId: number, qty: number) =>
  djangoShell(`from products.models import Product\nProduct.objects.filter(id=${productId}).update(quantity=${qty})\n`);

test.describe('API negatives - orders', { tag: ['@api-neg', '@orders'] }, () => {
  test('N1 retailer cancels a pending order: cancelled, stock restored, customer sees it @smoke', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const ct = await customerToken(api, C2_MOBILE);
    const P4 = seed.products.P4;
    const before = await productStock(api, rt, P4);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[P4, 2]], { addressId: seed.c2_address });
    expect(await productStock(api, rt, P4)).toBe(before - 2);

    const r = await api.post(`orders/${order.id}/cancel/`, { ...authed(rt), data: { reason: 'out of delivery range' } });
    expect(r.status(), await r.text()).toBe(200);
    expect(await r.json()).toMatchObject({ id: order.id, status: 'cancelled' });

    expect(await productStock(api, rt, P4)).toBe(before);
    expect(await getJson(api, `orders/${order.id}/`, ct)).toMatchObject({ status: 'cancelled' });
    // A second cancel is refused and changes nothing.
    const again = await api.post(`orders/${order.id}/cancel/`, { ...authed(rt), data: {} });
    expect(again.status()).toBe(400);
    expect(await again.json()).toMatchObject({ error: 'Order cannot be cancelled' });
    expect(await productStock(api, rt, P4)).toBe(before);
  });

  test('N2 two customers race for the last unit: exactly one order, the other gets 400, stock never negative', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const P3 = seed.products.P3;
    setStock(P3, 1);
    const [c1, c2] = await Promise.all([customerToken(api, C1_MOBILE), customerToken(api, C2_MOBILE)]);
    const results = await Promise.all([c1, c2].map((t) => tryPlaceOrder(api, t, seed.retailers.R1, [[P3, 1]], { mode: 'pickup' })));
    const codes = results.map((r) => r.status()).sort();
    expect(codes, await Promise.all(results.map((r) => r.text())).then((b) => b.join('\n'))).toEqual([201, 400]);
    const loser = results.find((r) => r.status() === 400)!;
    expect(JSON.stringify(await loser.json())).toMatch(
      /Not enough saleable stock for Sunflower Oil 1L|only 0(\.0+)? is available|only 1(\.0+)? is available/,
    );
    expect(await productStock(api, rt, P3)).toBe(0);
  });

  test('N3 retailer B cannot read, update or cancel retailer A\'s order', async ({ api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const r2 = await retailerToken(R2.username);
    const notFound = { error: 'Order not found' };

    const read = await api.get(`orders/${order.id}/`, authed(r2));
    expect(read.status()).toBe(404);
    expect(await read.json()).toEqual(notFound);
    const update = await api.patch(`orders/${order.id}/status/`, { ...authed(r2), data: { status: 'confirmed' } });
    expect(update.status()).toBe(404);
    expect(await update.json()).toEqual(notFound);
    const cancel = await api.post(`orders/${order.id}/cancel/`, { ...authed(r2), data: {} });
    expect(cancel.status()).toBe(404);
    expect(await cancel.json()).toEqual(notFound);

    const current = await getJson(api, 'orders/current/', r2);
    const rows = current.results ?? current;
    expect(rows.map((o: { id: number }) => o.id)).not.toContain(order.id);
    expect((await getJson(api, `orders/${order.id}/`, await retailerToken())).status).toBe('pending');
  });

  test('N4 customer token on retailer order endpoints is refused', async ({ api, seed }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const r = await api.patch(`orders/${order.id}/status/`, { ...authed(ct), data: { status: 'confirmed' } });
    expect(r.status()).toBe(403);
    expect(await r.json()).toEqual({ error: 'Only retailers can update order status' });
    expect((await getJson(api, `orders/${order.id}/`, ct)).status).toBe('pending');
  });

  test('N5 unauthenticated place-order and cart add are refused', async ({ api, seed }) => {
    const place = await api.post('orders/place/', { data: { retailer_id: String(seed.retailers.R1), delivery_mode: 'pickup', payment_mode: 'cash_pickup' } });
    expect(place.status()).toBe(401);
    expect(await place.json()).toEqual({ detail: 'Authentication credentials were not provided.' });
    const add = await api.post('cart/add/', { data: { product_id: seed.products.P4, quantity: 1 } });
    expect(add.status()).toBe(401);
    expect(await add.json()).toMatchObject({ detail: 'Authentication credentials were not provided.' });
  });

  test('N6 retailer token cannot place an order', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const r = await api.post('orders/place/', { ...authed(rt), data: { retailer_id: String(seed.retailers.R1), delivery_mode: 'pickup', payment_mode: 'cash_pickup' } });
    expect(r.status()).toBe(403);
    expect(await r.json()).toEqual({ error: 'Only customers can place orders' });
  });

  test('N7 bad cart quantities and unknown products are refused and the cart stays empty', async ({ api, seed }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const before = await getJson(api, 'cart/count/', ct);
    const cases: [unknown, unknown, Record<string, string[]>][] = [
      [seed.products.P4, 0, { quantity: ['Quantity must be greater than 0'] }],
      [seed.products.P4, -1, { quantity: ['Quantity must be greater than 0'] }],
      [seed.products.P4, 'abc', { quantity: ['A valid number is required.'] }],
      [99999999, 1, { product_id: ['Product not found or not available'] }],
    ];
    for (const [product_id, quantity, body] of cases) {
      const r = await api.post('cart/add/', { ...authed(ct), data: { product_id, quantity } });
      expect(r.status(), `${product_id} x ${quantity}`).toBe(400);
      expect(await r.json()).toEqual(body);
    }
    expect(await getJson(api, 'cart/count/', ct)).toEqual(before);
  });

  test('N8 delivery checkout with no address, and with an empty cart, is refused', async ({ api, seed }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const ordersBefore = (await getJson(api, 'orders/current/', ct)).count;
    const empty = await tryPlaceOrder(api, ct, seed.retailers.R1, [], { mode: 'pickup' });
    expect(empty.status()).toBe(400);
    expect(await empty.json()).toEqual({ non_field_errors: ['Cart is empty'] });

    const noAddress = await tryPlaceOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]]);
    expect(noAddress.status()).toBe(400);
    expect(await noAddress.json()).toEqual({ non_field_errors: ['Address is required for delivery orders'] });
    expect((await getJson(api, 'orders/current/', ct)).count).toBe(ordersBefore);
  });

  test('N9 more refused transitions: packed→confirmed, confirmed→delivered, retailer cancel after delivered', async ({ api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const rt = await retailerToken();
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    await advance(api, rt, order.id, ['confirmed']);
    const skip = await api.patch(`orders/${order.id}/status/`, { ...authed(rt), data: { status: 'delivered' } });
    expect(skip.status()).toBe(400);
    expect(await skip.json()).toEqual({ status: ["Cannot change status from 'confirmed' to 'delivered'"] });

    await advance(api, rt, order.id, ['packed']);
    const back = await api.patch(`orders/${order.id}/status/`, { ...authed(rt), data: { status: 'confirmed' } });
    expect(back.status()).toBe(400);
    expect(await back.json()).toEqual({ status: ["Cannot change status from 'packed' to 'confirmed'"] });

    await advance(api, rt, order.id, ['delivered']);
    const cancel = await api.post(`orders/${order.id}/cancel/`, { ...authed(rt), data: {} });
    expect(cancel.status()).toBe(400);
    expect(await cancel.json()).toEqual({ error: 'Order cannot be cancelled' });
    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('delivered');
  });
});

test.describe('API negatives - double submit and stale state', { tag: ['@api-neg', '@orders'] }, () => {
  test('N10 place-order submitted twice: one order, the repeat gets "Cart is empty", stock taken once', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const ct = await customerToken(api, C2_MOBILE);
    const P4 = seed.products.P4;
    const stockBefore = await productStock(api, rt, P4);
    const ordersBefore = (await getJson(api, 'orders/current/', ct)).count;

    await placeOrder(api, ct, seed.retailers.R1, [[P4, 2]], { mode: 'pickup' });
    const again = await tryPlaceOrder(api, ct, seed.retailers.R1, [], { mode: 'pickup' });
    expect(again.status()).toBe(400);
    expect(await again.json()).toEqual({ non_field_errors: ['Cart is empty'] });

    expect((await getJson(api, 'orders/current/', ct)).count).toBe(ordersBefore + 1);
    expect(await productStock(api, rt, P4)).toBe(stockBefore - 2);
  });

  // TODO: open a Jira ticket and swap 'NEW' for the key. Repro: add P4 x2 to C2's R1 cart, then POST
  // orders/place/ twice in parallel with the same body; the cart row is not locked (no select_for_update),
  // so both submits can read the full cart and both return 201 (two orders, stock taken twice).
  fixme('N11 two identical place-order requests at once: exactly one order, the repeat gets "Cart is empty"',
    known('NEW', 'parallel POST orders/place/ on one cart can create two orders: the cart is not locked during checkout'),
    async ({ api, seed, retailerToken }) => {
      const rt = await retailerToken();
      const ct = await customerToken(api, C2_MOBILE);
      const P4 = seed.products.P4;
      const stockBefore = await productStock(api, rt, P4);
      const ordersBefore = (await getJson(api, 'orders/current/', ct)).count;

      const add = await api.post('cart/add/', { ...authed(ct), data: { product_id: P4, quantity: 2 } });
      expect(add.status(), await add.text()).toBeLessThan(300);
      const results = await Promise.all([1, 2].map(() => tryPlaceOrder(api, ct, seed.retailers.R1, [], { mode: 'pickup' })));
      const codes = results.map((r) => r.status()).sort();
      expect(codes, await Promise.all(results.map((r) => r.text())).then((t) => t.join('\n'))).toEqual([201, 400]);
      const loser = results.find((r) => r.status() === 400)!;
      expect(await loser.json()).toMatchObject({ non_field_errors: ['Cart is empty'] });

      expect((await getJson(api, 'orders/current/', ct)).count).toBe(ordersBefore + 1);
      expect(await productStock(api, rt, P4)).toBe(stockBefore - 2);
    });

  test('N12 POS bill submitted twice for the last unit: one sale, the other "Not enough saleable stock"', async ({ api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const P3 = seed.products.P3;
    setStock(P3, 1);
    const results = await Promise.all([1, 2].map(() => posBill(api, rt, [[P3, 1, 'P3']], { cash: price('P3') })));
    const codes = results.map((r) => r.status()).sort();
    expect(codes, await Promise.all(results.map((r) => r.text())).then((b) => b.join('\n'))).toEqual([201, 400]);
    const loser = results.find((r) => r.status() === 400)!;
    expect(JSON.stringify(await loser.json())).toMatch(/Not enough saleable stock for Sunflower Oil 1L/);
    expect(await productStock(api, rt, P3)).toBe(0);
  });

  test('N13 price raised after add-to-cart: the order charges what the cart showed at checkout', async ({ api, seed }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const P4 = seed.products.P4;
    await customerCart(api, ct, seed.retailers.R1);
    const add = await api.post('cart/add/', { ...authed(ct), data: { product_id: P4, quantity: 1 } });
    expect(add.status(), await add.text()).toBeLessThan(300);
    djangoShell(`from products.models import Product\nProduct.objects.filter(id=${P4}).update(price=${price('P4') + 50})\n`);

    const shown = await customerCart(api, ct, seed.retailers.R1);
    const order = await placeOrder(api, ct, seed.retailers.R1, [], { mode: 'pickup' });
    expect(Number(order.total_amount)).toBe(Number(shown.discounted_total ?? shown.subtotal));
  });

  test('N14 an order the customer cancelled: still readable by them, hidden from others, frozen', async ({ api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const other = await customerToken(api, C1_MOBILE);
    const rt = await retailerToken();
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { mode: 'pickup' });
    const cancel = await api.post(`orders/${order.id}/cancel/`, { ...authed(ct), data: { reason: 'changed my mind' } });
    expect(cancel.status(), await cancel.text()).toBe(200);

    expect(await getJson(api, `orders/${order.id}/`, ct)).toMatchObject({ id: order.id, status: 'cancelled' });
    const peek = await api.get(`orders/${order.id}/`, authed(other));
    expect(peek.status()).toBe(404);
    expect(await peek.json()).toEqual({ error: 'Order not found' });
    const strangerCancel = await api.post(`orders/${order.id}/cancel/`, { ...authed(other), data: {} });
    expect(strangerCancel.status()).toBe(404);
    expect(await strangerCancel.json()).toMatchObject({ error: 'Order not found' });

    const again = await api.post(`orders/${order.id}/cancel/`, { ...authed(ct), data: {} });
    expect(again.status()).toBe(400);
    expect(await again.json()).toEqual({ error: 'Order cannot be cancelled' });
    const revive = await api.patch(`orders/${order.id}/status/`, { ...authed(rt), data: { status: 'confirmed' } });
    expect(revive.status()).toBe(400);
    expect(await revive.json()).toEqual({ status: ["Cannot change status from 'cancelled' to 'confirmed'"] });
    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('cancelled');
  });
});
