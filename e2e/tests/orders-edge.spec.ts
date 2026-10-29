/**
 * Order edge cases: cancels, rejects, item edit + customer approval, partial availability,
 * pickup vs delivery, slot rules, payment modes, notifications.
 * Confirmed→Packed (OE-373) and the raw approval label (OE-372) live in fixme.spec.ts, not here.
 */
import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { authed, customerLogin, customerToken, djangoShell, getJson, productStock, retailerLogin, sl1 } from '../helpers';
import { advance, fixme, known, placeOrder, price, tryPlaceOrder } from '../edge';
import { C2_MOBILE } from '../seed';

async function customerOrder(page: Page, orderId: number) {
  await customerLogin(page, C2_MOBILE);
  await page.goto(`${urls.customer}/orders/detail?id=${orderId}`);
  await expect(page.getByTestId('order-status-label')).toBeVisible();
}

async function retailerOrder(page: Page, orderId: number) {
  await retailerLogin(page);
  await page.goto(`${urls.retailer}/dashboard/orders/details?id=${orderId}`);
  await expect(page.getByTestId('order-status')).toBeVisible();
}

test.describe('Orders edge - cancel', { tag: ['@orders', '@orders-edge'] }, () => {
  test('E1 customer cancels a pending order: Cancelled by customer, stock back to 100 @customer', async ({ page, api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P3, 2]], { addressId: seed.c2_address });
    const rt = await retailerToken();
    expect(await productStock(api, rt, seed.products.P3)).toBe(98);

    await customerOrder(page, order.id);
    page.once('dialog', (d) => d.accept());
    const cancelled = page.waitForResponse((r) => r.url().includes(`/orders/${order.id}/cancel/`));
    await page.getByRole('button', { name: 'Cancel Order' }).click();
    expect((await cancelled).status()).toBe(200);
    await expect(page.getByTestId('order-status-label')).toHaveText(/cancelled/i);
    await expect(page.getByText('By customer')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cancel Order' })).toHaveCount(0);

    const body = await getJson(api, `orders/${order.id}/`, rt);
    expect(body.status).toBe('cancelled');
    expect(body.cancelled_by).toBe('customer');
    expect(await productStock(api, rt, seed.products.P3)).toBe(100);
    // A second cancel is refused.
    expect((await api.post(`orders/${order.id}/cancel/`, { ...authed(ct), data: {} })).status()).toBe(400);
  });

  // Known API bug OE-383: PATCH orders/{id}/status/ {status:'cancelled'} drops cancelled_by and reason; UI uses /cancel/.
  test('E2 retailer cancels a confirmed order from the UI: By Retailer, customer sees it, stock restored @retailer', async ({ page, api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 3]], { addressId: seed.c2_address });
    const rt = await retailerToken();
    await advance(api, rt, order.id, ['confirmed']);

    await retailerOrder(page, order.id);
    await page.getByRole('button', { name: 'CANCEL ORDER' }).click();
    const cancelled = page.waitForResponse((r) => r.url().includes(`/orders/${order.id}/cancel/`));
    await page.getByRole('button', { name: 'Yes, Cancel Order' }).click();
    expect((await cancelled).status()).toBe(200);
    await expect(page.getByTestId('order-status')).toHaveText(/cancelled/i);
    await expect(page.getByText('By Retailer')).toBeVisible();

    const body = await getJson(api, `orders/${order.id}/`, ct);
    expect(body.status).toBe('cancelled');
    expect(body.cancelled_by).toBe('retailer');
    expect(await productStock(api, rt, seed.products.P4)).toBe(100);
  });

  test('E3 a packed order cannot be cancelled: no button for the customer, API 400 @customer', async ({ page, api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    await advance(api, await retailerToken(), order.id, ['confirmed', 'processing', 'packed']);

    await customerOrder(page, order.id);
    await expect(page.getByTestId('order-status-label')).toHaveText(/packed/i);
    await expect(page.getByRole('button', { name: 'Cancel Order' })).toHaveCount(0);
    expect((await api.post(`orders/${order.id}/cancel/`, { ...authed(ct), data: {} })).status()).toBe(400);
    expect((await getJson(api, `orders/${order.id}/`, ct)).status).toBe('packed');
  });

  fixme('E4 retailer can cancel an order waiting for customer approval (UI offers CANCEL ORDER) @retailer',
    known('OE-377', 'CANCEL ORDER is shown on a waiting_for_customer_approval order, but POST /cancel/ returns 400 "Order cannot be cancelled"'),
    async ({ page, api, seed, retailerToken }) => {
      const ct = await customerToken(api, C2_MOBILE);
      const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P3, 2]], { addressId: seed.c2_address });
      const rt = await retailerToken();
      const line = order.items[0].id;
      expect((await api.post(`orders/${order.id}/modify/`, { ...authed(rt), data: { items: [{ id: line, quantity: 1 }] } })).status()).toBe(200);

      await retailerOrder(page, order.id);
      await page.getByRole('button', { name: 'CANCEL ORDER' }).click();
      const cancelled = page.waitForResponse((r) => r.url().includes(`/orders/${order.id}/cancel/`));
      await page.getByRole('button', { name: 'Yes, Cancel Order' }).click();
      expect((await cancelled).status()).toBe(200);
      expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('cancelled');
    });
});

test.describe('Orders edge - item edit and customer approval', { tag: ['@orders', '@orders-edge'] }, () => {
  // Partial availability: R1 only has 1 of the 2 oils and adds 2 biscuits instead.
  const editedTotal = price('P3') * 1 + price('P4') * 2; // 165 + 60 = 225

  async function placeAndEdit(api: Parameters<typeof placeOrder>[0], seed: { retailers: { R1: number }; products: Record<string, number>; c2_address: number }, rt: string) {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P3, 2]], { addressId: seed.c2_address });
    expect(Number(order.total_amount)).toBe(price('P3') * 2);
    const response = await api.post(`orders/${order.id}/modify/`, {
      ...authed(rt),
      data: { items: [{ id: order.items[0].id, quantity: 1 }, { product_id: seed.products.P4, quantity: 2 }] },
    });
    expect(response.status(), await response.text()).toBe(200);
    const body = await response.json();
    expect(body.status).toBe('waiting_for_customer_approval');
    expect(Number(body.total_amount)).toBe(editedTotal);
    return { order, ct };
  }

  test('E5 partial availability: edited order (P3 2→1, +P4×2) accepted by the customer is confirmed at ₹225.00 @customer', async ({ page, api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const { order } = await placeAndEdit(api, seed, rt);

    await customerOrder(page, order.id);
    await expect(page.getByTestId('order-total')).toHaveText(`₹${editedTotal.toFixed(2)}`);
    const answered = page.waitForResponse((r) => r.url().includes(`/orders/${order.id}/confirm_modification/`));
    await page.getByRole('button', { name: 'Accept Changes' }).click();
    expect((await answered).status()).toBe(200);
    await expect(page.getByTestId('order-status-label')).toHaveText(/confirmed/i);
    await expect(page.getByRole('button', { name: 'Accept Changes' })).toHaveCount(0);

    const body = await getJson(api, `orders/${order.id}/`, rt);
    expect(body.status).toBe('confirmed');
    expect(Number(body.total_amount)).toBe(editedTotal);
    expect(await productStock(api, rt, seed.products.P3)).toBe(99);
    expect(await productStock(api, rt, seed.products.P4)).toBe(98);
  });

  test('E6 customer rejects the edit: order cancelled and all stock restored @customer', async ({ page, api, seed, retailerToken }) => {
    const rt = await retailerToken();
    const { order } = await placeAndEdit(api, seed, rt);

    await customerOrder(page, order.id);
    const answered = page.waitForResponse((r) => r.url().includes(`/orders/${order.id}/confirm_modification/`));
    await page.getByRole('button', { name: 'Reject & Cancel' }).click();
    expect((await answered).status()).toBe(200);
    await expect(page.getByTestId('order-status-label')).toHaveText(/cancelled/i);

    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('cancelled');
    expect(await productStock(api, rt, seed.products.P3)).toBe(100);
    expect(await productStock(api, rt, seed.products.P4)).toBe(100);
  });

  fixme('E7 a rejected edit records who cancelled (customer) @customer @retailer',
    known('OE-378', 'confirm_modification action=reject cancels the order with cancelled_by=null, so neither app shows "By Customer"'),
    async ({ page, api, seed, retailerToken }) => {
      const rt = await retailerToken();
      const { order, ct } = await placeAndEdit(api, seed, rt);
      expect((await api.post(`orders/${order.id}/confirm_modification/`, { ...authed(ct), data: { action: 'reject' } })).status()).toBe(200);
      expect((await getJson(api, `orders/${order.id}/`, rt)).cancelled_by).toBe('customer');
      await retailerOrder(page, order.id);
      await expect(page.getByText('By Customer')).toBeVisible();
    });

  test('E8 only pending orders can be edited @retailer', async ({ api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const rt = await retailerToken();
    await advance(api, rt, order.id, ['confirmed']);
    const response = await api.post(`orders/${order.id}/modify/`, { ...authed(rt), data: { items: [{ id: order.items[0].id, quantity: 5 }] } });
    expect(response.status()).toBe(400);
    expect(await response.text()).toContain('Only pending orders can be modified');
    expect(Number((await getJson(api, `orders/${order.id}/`, rt)).total_amount)).toBe(price('P4'));
  });
});

test.describe('Orders edge - pickup, payment modes, slots', { tag: ['@orders', '@orders-edge'] }, () => {
  test('E9 pickup order: wrong pickup code is refused, the right one completes it @retailer', async ({ page, api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { mode: 'pickup' });
    expect(order.delivery_mode).toBe('pickup');
    expect(Number(order.delivery_fee)).toBe(0);
    const code: string = order.pickup_code;
    expect(code).toMatch(/^\d{6}$/);
    const rt = await retailerToken();
    await advance(api, rt, order.id, ['confirmed', 'processing', 'packed']);

    await retailerOrder(page, order.id);
    await expect(page.getByText("Pickup window")).toBeVisible();
    const pickedUp = page.getByTestId('order-status-next-delivered');
    await expect(pickedUp).toHaveText('MARK AS PICKED UP');

    const wrong = code === '111111' ? '222222' : '111111';
    await pickedUp.click();
    await page.getByLabel('Pickup code').fill(wrong);
    const refused = page.waitForResponse((r) => r.url().includes(`/orders/inbox/${order.id}/actions/`));
    await page.getByRole('button', { name: 'Mark as picked up' }).click();
    expect((await refused).status()).toBe(400);
    expect((await getJson(api, `orders/${order.id}/`, rt)).status).toBe('packed');

    await page.reload();
    await page.getByTestId('order-status-next-delivered').click();
    await page.getByLabel('Pickup code').fill(code);
    const accepted = page.waitForResponse((r) => r.url().includes(`/orders/inbox/${order.id}/actions/`));
    await page.getByRole('button', { name: 'Mark as picked up' }).click();
    expect((await accepted).status()).toBe(200);
    await expect(page.getByTestId('order-status')).toHaveText(/delivered|picked/i);
    expect((await getJson(api, `orders/${order.id}/`, ct)).status).toBe('delivered');
  });

  test('E10 payment mode must match the fulfilment mode @customer', async ({ api, seed }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const deliveryPickupCash = await tryPlaceOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address, pay: 'cash_pickup' });
    expect(deliveryPickupCash.status()).toBe(400);
    expect(await deliveryPickupCash.text()).toContain('Invalid payment mode for delivery');
    const pickupCod = await tryPlaceOrder(api, ct, seed.retailers.R1, [], { mode: 'pickup', pay: 'cash' });
    expect(pickupCod.status()).toBe(400);
    expect(await pickupCod.text()).toContain('Invalid payment mode for pickup');
  });

  test('E11 UPI: bad ref refused, 12-digit ref submitted, retailer verifies, customer sees Verified and locked @customer @retailer', async ({ page, api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address, pay: 'upi' });

    await customerOrder(page, order.id);
    const ref = page.getByPlaceholder('Enter 12-digit UPI Ref No.');
    await ref.fill('12345');
    await page.getByRole('button', { name: 'Submit Details' }).click();
    await expect(page.getByText('Invalid ID format')).toBeVisible();
    expect((await getJson(api, `orders/${order.id}/`, ct)).payment_reference_id).toBeFalsy();

    await ref.fill('123456789012');
    const submitted = page.waitForResponse((r) => r.url().includes(`/orders/${order.id}/submit_payment/`));
    await page.getByRole('button', { name: 'Submit Details' }).click();
    expect((await submitted).status()).toBe(200);
    await expect(page.getByText('123456789012')).toBeVisible();
    await expect(page.getByText('Pending Verification')).toBeVisible();

    const rt = await retailerToken();
    const verify = await api.post(`orders/${order.id}/verify_payment/`, { ...authed(rt), data: { action: 'verify' } });
    expect(verify.status()).toBe(200);
    await page.reload();
    await expect(page.getByText('Verified', { exact: true })).toBeVisible();
    await expect(page.getByText('Payment verified and locked')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit' })).toHaveCount(0);
    const edit = await api.post(`orders/${order.id}/submit_payment/`, { ...authed(ct), data: { payment_reference_id: '123456789013' } });
    expect(edit.status()).toBe(400);
  });

  fixme('E12 retailer cannot verify a UPI payment before the customer submits a transaction ID @retailer',
    known('OE-379', 'a new UPI order starts as payment_status=pending_verification with no reference; the retailer UI shows Verify and verify_payment returns 200'),
    async ({ api, seed, retailerToken }) => {
      const ct = await customerToken(api, C2_MOBILE);
      const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address, pay: 'upi' });
      expect(order.payment_status).not.toBe('pending_verification');
      const verify = await api.post(`orders/${order.id}/verify_payment/`, { ...authed(await retailerToken()), data: { action: 'verify' } });
      expect(verify.status()).toBe(400);
    });

  test('E13 slot rules: outside hours, off-grid and past slots are refused @customer', async ({ api, seed }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const day = sl1().start.slice(0, 10);
    const cases: [string, string][] = [
      [`${day}T13:00:00+05:30`, 'outside operating hours'],
      [`${day}T10:15:00+05:30`, '30-minute boundaries'],
      ['2020-01-01T10:00:00+05:30', 'in the past'],
    ];
    let first = true;
    for (const [slotStart, message] of cases) {
      const response = await tryPlaceOrder(api, ct, seed.retailers.R1, first ? [[seed.products.P4, 1]] : [], { addressId: seed.c2_address, slotStart });
      first = false;
      expect(response.status(), slotStart).toBe(400);
      expect(await response.text()).toContain(message);
    }
  });

  test('E14 a full slot is shown unavailable and refuses another order @customer', async ({ api, seed }) => {
    djangoShell(`from retailers.models import RetailerProfile\nRetailerProfile.objects.filter(id=${seed.retailers.R1}).update(fulfillment_slot_capacity=1)\n`);
    const ct = await customerToken(api, C2_MOBILE);
    await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const slots = await getJson(api, `retailers/${seed.retailers.R1}/fulfillment-slots/?delivery_mode=delivery`, ct);
    const slot = slots.slots.find((s: { slot_start_local: string }) => s.slot_start_local === sl1().start);
    expect(slot?.is_available ?? false).toBe(false);
    const second = await tryPlaceOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], {
      addressId: seed.c2_address, slotStart: `${sl1().start}`,
    });
    expect(second.status()).toBe(400);
    expect(await second.json()).toEqual({ fulfillment_slot_start: ['Fulfillment slot is fully booked'] });
  });

  // Known minor bug OE-384: customer notifications carry null order_id/order_number (order number only in the title).
  test('E15 customer gets confirmed and cancelled notifications for the order @customer', async ({ api, seed, retailerToken }) => {
    const ct = await customerToken(api, C2_MOBILE);
    const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
    const rt = await retailerToken();
    await advance(api, rt, order.id, ['confirmed']);
    expect((await api.post(`orders/${order.id}/cancel/`, { ...authed(rt), data: { reason: 'E2E out of stock' } })).status()).toBe(200);
    const messages = async () => (await getJson(api, 'customer/notifications/', ct)).results
      .filter((n: { title: string }) => n.title.includes(order.order_number))
      .map((n: { message: string }) => n.message);
    await expect.poll(messages).toEqual(expect.arrayContaining(['Your order has been confirmed', 'Your order has been cancelled']));
  });

  fixme('E16 cancelling through PATCH status/ records who cancelled and the reason, like /cancel/ @retailer',
    known('OE-383', "PATCH orders/{id}/status/ {status:'cancelled', reason} leaves cancelled_by null and drops the reason"),
    async ({ api, seed, retailerToken }) => {
      const ct = await customerToken(api, C2_MOBILE);
      const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
      const rt = await retailerToken();
      const r = await api.patch(`orders/${order.id}/status/`, { ...authed(rt), data: { status: 'cancelled', reason: 'E2E out of stock' } });
      expect(r.status(), await r.text()).toBe(200);
      const body = await getJson(api, `orders/${order.id}/`, rt);
      expect(body).toMatchObject({ status: 'cancelled', cancelled_by: 'retailer', cancellation_reason: 'E2E out of stock' });
    });

  fixme('E17 order notifications carry the order id and number @customer',
    known('OE-384', 'customer/notifications/ entries for an order have order_id and order_number null'),
    async ({ api, seed, retailerToken }) => {
      const ct = await customerToken(api, C2_MOBILE);
      const order = await placeOrder(api, ct, seed.retailers.R1, [[seed.products.P4, 1]], { addressId: seed.c2_address });
      const rt = await retailerToken();
      expect((await api.post(`orders/${order.id}/cancel/`, { ...authed(rt), data: { reason: 'E2E out of stock' } })).status()).toBe(200);
      const mine = async () => (await getJson(api, 'customer/notifications/', ct)).results
        .filter((n: { title: string }) => n.title.includes(order.order_number))
        .map((n: { order_id: number | null; order_number: string | null }) => [n.order_id, n.order_number]);
      await expect.poll(mine).toEqual([[order.id, order.order_number]]);
    });
});
