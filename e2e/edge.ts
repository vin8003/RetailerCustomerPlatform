/**
 * Helpers for orders-edge, khata-ledger, reports and settings specs.
 * API-only setup; the specs assert outcomes on screen and through the API.
 */
import { type APIRequestContext } from '@playwright/test';
import { expect, test } from './fixtures';
import { addToCart, authed, getJson, sl1 } from './helpers';
import { PRODUCT } from './seed';

const JIRA = 'https://vin8003.atlassian.net/browse/';
/** Bug annotation. `ticket` is a Jira key, or 'NEW' while no ticket exists yet. */
export const known = (ticket: string, bug: string) => ({
  annotation: { type: 'bug', description: ticket === 'NEW' ? `(no ticket yet) ${bug}` : `${JIRA}${ticket} ${bug}` },
});
/** E2E_RUN_FIXME=1 runs the known-broken tests too. */
export const fixme = process.env.E2E_RUN_FIXME ? test : test.fixme;

export type ProductKey = keyof typeof PRODUCT;
export const price = (key: ProductKey) => Number(PRODUCT[key].price);

type PlaceOptions = {
  mode?: 'delivery' | 'pickup';
  pay?: 'cash' | 'upi' | 'cash_pickup';
  addressId?: number;
  slotStart?: string;
};

/** POST orders/place/ without asserting the status (for rule checks). */
export async function tryPlaceOrder(
  api: APIRequestContext, token: string, retailerId: number, items: [number, number][], opts: PlaceOptions = {},
) {
  for (const [productId, qty] of items) await addToCart(api, token, productId, qty);
  const mode = opts.mode ?? 'delivery';
  let slotStart = opts.slotStart;
  if (!slotStart) {
    const slots = await getJson(api, `retailers/${retailerId}/fulfillment-slots/?delivery_mode=${mode}`, token);
    const slot = slots.slots.find((s: { slot_start_local: string }) => s.slot_start_local === sl1().start);
    expect(slot, 'SL1 slot offered').toBeTruthy();
    slotStart = slot.slot_start;
  }
  const data: Record<string, unknown> = {
    retailer_id: String(retailerId),
    delivery_mode: mode,
    payment_mode: opts.pay ?? (mode === 'pickup' ? 'cash_pickup' : 'cash'),
    special_instructions: '',
    use_reward_points: false,
    coupon_code: null,
    fulfillment_slot_start: slotStart,
  };
  if (mode === 'delivery') data.address_id = opts.addressId;
  return api.post('orders/place/', { ...authed(token), data });
}

export async function placeOrder(
  api: APIRequestContext, token: string, retailerId: number, items: [number, number][], opts: PlaceOptions = {},
) {
  const response = await tryPlaceOrder(api, token, retailerId, items, opts);
  expect(response.status(), await response.text()).toBe(201);
  const body = await response.json();
  return body.order ?? body;
}

/** Walk an order forward through the given statuses as the retailer. */
export async function advance(api: APIRequestContext, token: string, orderId: number, statuses: string[]) {
  for (const status of statuses) {
    const response = await api.patch(`orders/${orderId}/status/`, {
      ...authed(token),
      data: { status, delivery_person_name: 'E2E Rider', delivery_person_phone: '+919999900000' },
    });
    expect(response.status(), `${status}: ${await response.text()}`).toBe(200);
  }
}

/** POS bill through the API. `payment` is the split, e.g. { cash: 165 }. */
export async function posBill(
  api: APIRequestContext, token: string, items: [number, number, ProductKey][],
  payment: Record<string, number>, customer?: { mobile: string; name: string },
) {
  const data: Record<string, unknown> = {
    items: items.map(([product_id, quantity, key]) => ({ product_id, quantity, unit_price: price(key) })),
    payment_details: payment,
  };
  if (customer) Object.assign(data, { customer_mobile: customer.mobile, customer_name: customer.name });
  return api.post('products/erp/pos-checkout/', { ...authed(token), data });
}
