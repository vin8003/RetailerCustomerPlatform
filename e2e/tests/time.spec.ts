import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { addToCart, customerLogin, customerToken, customerUseSeedCity, placeCodOrder, retailerLogin, sl1 } from '../helpers';

const C2_PHONE = '9000000002';

/** Replace every created_at in the order-history response with `iso`: the order is placed "now" on the pinned clock. */
async function pinOrderCreatedAt(page: Page, iso: string) {
  await page.unroute('**/api/orders/history/**');
  await page.route('**/api/orders/history/**', async (route) => {
    const response = await route.fetch();
    const rewrite = (node: unknown): unknown => {
      if (Array.isArray(node)) return node.map(rewrite);
      if (node && typeof node === 'object') {
        return Object.fromEntries(
          Object.entries(node).map(([k, v]) => [k, k === 'created_at' ? iso : rewrite(v)]),
        );
      }
      return node;
    };
    await route.fulfill({ response, json: rewrite(await response.json()) });
  });
}

test('T1 order date flips 28 Oct → 29 Oct exactly at IST midnight @T1', async ({ page, api, seed }) => {
  const token = await customerToken(api, C2_PHONE);
  await addToCart(api, token, seed.products.P4, 1);
  await placeCodOrder(api, token, seed.retailers.R1, seed.c2_address);

  await customerUseSeedCity(page);
  await customerLogin(page, C2_PHONE);

  const beforeMidnight = new Date('2026-10-28T23:59:30+05:30');
  await page.clock.setFixedTime(beforeMidnight);
  await pinOrderCreatedAt(page, beforeMidnight.toISOString());
  await page.goto(`${urls.customer}/orders`);
  await expect(page.getByTestId('order-card').first()).toContainText('28 Oct 2026');

  const afterMidnight = new Date('2026-10-29T00:00:30+05:30');
  await page.clock.setFixedTime(afterMidnight);
  await pinOrderCreatedAt(page, afterMidnight.toISOString());
  await page.reload();
  await expect(page.getByTestId('order-card').first()).toContainText('29 Oct 2026');
});

test('T2 next-day slot shows the correct IST date on both apps at 23:59:30 IST @T2', async ({ page, context, api, seed }) => {
  // Pin both apps to 23:59:30 IST today: the browser clock is 30s from the IST date change.
  const todayIst = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
  const pinned = new Date(`${todayIst}T23:59:30+05:30`);
  const slot = sl1(); // computed from the real clock, which is the server's view of "tomorrow"
  expect(sl1(pinned.getTime()).start, 'pinned and real clocks agree on the IST date').toBe(slot.start);
  await context.clock.setFixedTime(pinned);

  const token = await customerToken(api, C2_PHONE);
  await addToCart(api, token, seed.products.P4, 1);
  const order = await placeCodOrder(api, token, seed.retailers.R1, seed.c2_address);

  await customerUseSeedCity(page);
  await customerLogin(page, C2_PHONE);
  await page.goto(`${urls.customer}/orders/detail?id=${order.id}`);
  await expect(page.getByTestId('order-slot')).toHaveText(slot.customerLabel);

  // The picker labels the next IST day as Tomorrow.
  await page.goto(`${urls.customer}/retailer?id=${seed.retailers.R1}`);
  await page.getByTestId(`add-to-cart-${seed.products.P4}`).first().click();
  await expect(page.getByTestId(`cart-qty-${seed.products.P4}`).first()).toHaveText('1');
  await page.goto(`${urls.customer}/cart`);
  await page.getByTestId('cart-checkout').click();
  await page.waitForURL('**/checkout**');
  await page.getByTestId('slot-picker-open').click();
  const ymd = slot.start.slice(0, 10);
  await expect(page.getByTestId(`slot-day-${ymd}`)).toContainText('Tomorrow');

  const retailer = await context.newPage();
  await retailerLogin(retailer);
  await retailer.goto(`${urls.retailer}/dashboard/orders/details?id=${order.id}`);
  await expect(retailer.getByTestId('order-slot')).toHaveText(slot.retailerLabel);
});
