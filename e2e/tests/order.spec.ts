import { type Page } from '@playwright/test';
import { test, expect, urls } from '../fixtures';
import { sl1, customerLogin, customerUseSeedCity, getJson, retailerLogin } from '../helpers';

// Journey B: C2 orders P3 x2 + P4 x1 = ₹360.00 (COD, SL1) from R1; R1 walks it to delivered.
// SL1 is the 10:00–12:00 IST window; the platform books it as 30-minute slots, so we book 10:00–10:30 next day.

const C2_PHONE = '9000000002';
const RAW_ENUM = /[a-z]+_[a-z_]+|[A-Z]+_[A-Z_]+/;

/** SL1 = tomorrow (IST) 10:00. Labels are built the way each app formats them. */
async function placeOrder(page: Page, p3: number, p4: number, addressId: number): Promise<number> {
  await customerUseSeedCity(page);
  await customerLogin(page, C2_PHONE);
  await page.goto(`${urls.customer}/retailers`);
  await page.getByText('E2E Kirana').first().click();
  await page.waitForURL('**/retailer?id=*');

  await page.getByTestId(`add-to-cart-${p3}`).first().click();
  await page.getByTestId(`cart-increment-${p3}`).first().click();
  await expect(page.getByTestId(`cart-qty-${p3}`).first()).toHaveText('2');
  await page.getByTestId(`add-to-cart-${p4}`).first().click();
  await expect(page.getByTestId(`cart-qty-${p4}`).first()).toHaveText('1');

  await page.goto(`${urls.customer}/cart`);
  await page.getByTestId('cart-checkout').click();
  await page.waitForURL('**/checkout**');

  await page.getByTestId('slot-picker-open').click();
  await page.locator(`[data-testid="slot-option"][data-slot-start="${sl1().start}"]`).click();
  await page.getByTestId('slot-confirm').click();
  await expect(page.getByTestId('slot-summary')).toContainText('10:00');
  await page.getByTestId(`checkout-address-${addressId}`).click();
  await page.getByTestId('checkout-pay-cod').click();
  await expect(page.getByTestId('checkout-total')).toHaveText('₹360.00');

  const placed = page.waitForResponse((r) => r.url().includes('/orders/place/') && r.request().method() === 'POST');
  await page.getByTestId('checkout-place-order').click();
  expect((await placed).status()).toBe(201);
  await page.waitForURL('**/orders/detail?id=*');
  return Number(new URL(page.url()).searchParams.get('id'));
}

/** Reload My Orders and the order detail, assert the human label on both. */
async function expectCustomerLabel(page: Page, orderId: number, listLabel: string, detailLabel: string) {
  await page.goto(`${urls.customer}/orders`);
  const status = page.locator(`[data-testid="order-card"][data-order-id="${orderId}"]`).getByTestId('order-card-status');
  // The list renders status words with CSS `text-transform: capitalize`, so compare the DOM text case-insensitively.
  await expect(status).toHaveText(new RegExp(`^${listLabel}$`, 'i'));
  expect(await status.innerText()).not.toMatch(RAW_ENUM);

  await page.goto(`${urls.customer}/orders/detail?id=${orderId}`);
  await expect(page.getByTestId('order-status-label')).toHaveText(detailLabel);
  await expect(page.getByTestId('order-total')).toHaveText('₹360.00');
  await expect(page.getByTestId('order-slot')).toHaveText(sl1().customerLabel);
}

async function expectRetailerView(page: Page, orderId: number) {
  await page.goto(`${urls.retailer}/dashboard/orders/details?id=${orderId}`);
  await expect(page.getByTestId('order-total')).toHaveText('₹360.00');
  await expect(page.getByTestId('order-slot')).toHaveText(sl1().retailerLabel);
  await expect(page.getByText('Sunflower Oil 1L').filter({ visible: true }).first()).toBeVisible();
  await expect(page.getByText('Biscuit pack').filter({ visible: true }).first()).toBeVisible();
}

test('B1–B4 customer order walks pending → confirmed → packed → out for delivery → delivered @B1 @B2 @B3 @B4', async ({ context, seed, api, retailerToken }) => {
  const customer = await context.newPage();
  const retailer = await context.newPage();
  const token = await retailerToken('e2e_retailer');

  let orderId = 0;
  await test.step('B1 place order', async () => {
    orderId = await placeOrder(customer, seed.products.P3, seed.products.P4, seed.c2_address);
    const order = await getJson(api, `orders/${orderId}/`, token);
    expect(Number(order.total_amount)).toBe(360);
    expect(order.status).toBe('pending');
    await expectCustomerLabel(customer, orderId, 'Pending', 'Pending');
    await retailerLogin(retailer);
    await expectRetailerView(retailer, orderId);
  });

  await test.step('B2 retailer accepts', async () => {
    await retailer.getByTestId('order-status-next-confirmed').click();
    await retailer.getByTestId('order-confirm-submit').click();
    await expect(retailer.getByTestId('order-status')).toHaveText('CONFIRMED');
    await expectCustomerLabel(customer, orderId, 'Confirmed', 'Confirmed');
    await expectRetailerView(retailer, orderId);
  });

  await test.step('B3 retailer packs', async () => {
    // Goes via Processing: the direct Confirmed → Packed the UI offers is a known 400 (fixme F9).
    await retailer.getByTestId('order-status-next-processing').click();
    await expect(retailer.getByTestId('order-status')).toHaveText('PROCESSING');
    await expectCustomerLabel(customer, orderId, 'processing', 'Being prepared');
    await retailer.getByTestId('order-status-next-packed').click();
    await expect(retailer.getByTestId('order-status')).toHaveText('PACKED');
    await expectCustomerLabel(customer, orderId, 'Packed', 'Packed — preparing handoff');
    await expectRetailerView(retailer, orderId);
  });

  await test.step('B4 retailer dispatches, then delivers', async () => {
    await retailer.getByTestId('order-status-next-out_for_delivery').click();
    await retailer.getByLabel('Delivery person name').fill('E2E Rider');
    await retailer.getByLabel('Delivery person phone').fill('9100000009');
    await retailer.getByTestId('order-dispatch-submit').click();
    await expect(retailer.getByTestId('order-status')).toHaveText('OUT_FOR_DELIVERY');
    await expectCustomerLabel(customer, orderId, 'Out For Delivery', 'Out for delivery');

    await expectRetailerView(retailer, orderId);
    await retailer.getByTestId('order-status-next-delivered').click();
    await expect(retailer.getByTestId('order-status')).toHaveText('DELIVERED');
    await expectCustomerLabel(customer, orderId, 'Delivered', 'Delivered');
    await expectRetailerView(retailer, orderId);

    const order = await getJson(api, `orders/${orderId}/`, token);
    expect(order.status).toBe('delivered');
    expect(Number(order.total_amount)).toBe(360);
    expect(order.payment_mode).toBe('cash');
    expect(Number(order.cash_amount)).toBe(360);
  });

  await test.step('regression: order list filters render on both apps', async () => {
    await customer.goto(`${urls.customer}/orders`);
    await customer.getByTestId('orders-filter-delivered').click();
    await expect(customer.locator(`[data-testid="order-card"][data-order-id="${orderId}"]`)).toBeVisible();
    await customer.getByTestId('orders-filter-pending').click();
    await expect(customer.locator(`[data-testid="order-card"][data-order-id="${orderId}"]`)).toHaveCount(0);

    const { order_number } = await getJson(api, `orders/${orderId}/`, token);
    await retailer.goto(`${urls.retailer}/dashboard/orders`);
    await retailer.getByRole('tab', { name: 'Delivered', exact: true }).click();
    await expect(retailer.getByText(order_number).filter({ visible: true }).first()).toBeVisible();
    await retailer.getByRole('tab', { name: 'Pending', exact: true }).click();
    await expect(retailer.getByText(order_number).filter({ visible: true })).toHaveCount(0);
  });
});
