import { test, expect } from '../fixtures';
import { getJson, khataBalance, posCheckoutResponse, productStock, retailerLogin } from '../helpers';
import { BARCODE, attachCustomer, openPos, scan, scanCommonCart } from '../pos';
import { C1_MOBILE, R2 } from '../seed';


test.describe('Journey A - retailer POS bill (R1)', { tag: ['@retailer', '@pos', '@khata'] }, () => {
  test.beforeEach(async ({ page }) => {
    await retailerLogin(page);
    await openPos(page);
  });

  test('A1 UPI bill: rescans increment qty, total 620, stock decremented, no khata', async ({ page, api, seed, retailerToken }) => {
    await scanCommonCart(page);
    await page.getByTestId('pos-pay-upi').click();
    const checkout = posCheckoutResponse(page);
    await page.getByTestId('pos-complete-bill').click();
    const response = await checkout;
    expect(response.status()).toBe(201);
    const { order } = await response.json();

    await expect(page.getByTestId('pos-checkout-complete')).toBeVisible();
    await expect(page.getByTestId('pos-paid-total')).toHaveText('₹620');

    const token = await retailerToken();
    const saved = await getJson(api, `orders/${order.id}/`, token);
    expect(saved.total_amount).toBe('620.00');
    expect(saved.payment_mode).toBe('upi');
    expect(Number(saved.upi_amount)).toBe(620);
    expect(Number(saved.credit_amount)).toBe(0);
    expect(await productStock(api, token, seed.products.P1)).toBe(99);
    expect(await productStock(api, token, seed.products.P2)).toBe(98);
    expect(await productStock(api, token, seed.products.P4)).toBe(97);
    expect(await khataBalance(api, token, seed.customers.C1)).toBe(500);
  });

  test('A2 khata bill for C1: R1 outstanding 1120, R2 stays 1000, one ledger debit 620', async ({ page, api, seed, retailerToken }) => {
    await scanCommonCart(page);
    await attachCustomer(page, C1_MOBILE);
    await page.getByTestId('pos-pay-credit').click();
    const checkout = posCheckoutResponse(page);
    await page.getByTestId('pos-complete-bill').click();
    expect((await checkout).status()).toBe(201);
    await expect(page.getByTestId('pos-paid-total')).toHaveText('₹620');

    const r1 = await retailerToken();
    expect(await khataBalance(api, r1, seed.customers.C1)).toBe(1120);
    expect(await khataBalance(api, await retailerToken(R2.username), seed.customers.C1)).toBe(1000);
    const ledger = await getJson(api, `customer/retailer/ledger/${seed.customers.C1}/`, r1);
    expect(ledger.results).toHaveLength(1);
    expect(Number(ledger.results[0].amount)).toBe(620);
  });

  test('A3 split UPI 300 + khata 320: R1 outstanding 820; 300 + 300 is blocked', async ({ page, api, seed, retailerToken }) => {
    await scanCommonCart(page);
    await attachCustomer(page, C1_MOBILE);
    await page.getByTestId('pos-pay-split').click();
    await page.getByTestId('pos-split-cash').fill('0');
    await page.getByTestId('pos-split-upi').fill('300');
    await page.getByTestId('pos-split-credit').fill('300');
    await expect(page.getByTestId('pos-split-mismatch')).toContainText('must be ₹620');

    let checkoutCalls = 0;
    page.on('request', (r) => { if (r.url().includes('/erp/pos-checkout/')) checkoutCalls += 1; });
    await page.getByTestId('pos-complete-bill').click();
    await expect(page.getByText('does not match bill total')).toBeVisible();
    expect(checkoutCalls).toBe(0);

    await page.getByTestId('pos-split-credit').fill('320');
    await expect(page.getByTestId('pos-split-mismatch')).toHaveCount(0);
    const checkout = posCheckoutResponse(page);
    await page.getByTestId('pos-complete-bill').click();
    const response = await checkout;
    expect(response.status()).toBe(201);
    const { order } = await response.json();
    await expect(page.getByTestId('pos-paid-total')).toHaveText('₹620');

    const r1 = await retailerToken();
    const saved = await getJson(api, `orders/${order.id}/`, r1);
    expect(saved.total_amount).toBe('620.00');
    expect(Number(saved.upi_amount)).toBe(300);
    expect(Number(saved.credit_amount)).toBe(320);
    expect(await khataBalance(api, r1, seed.customers.C1)).toBe(820);
    expect(await khataBalance(api, await retailerToken(R2.username), seed.customers.C1)).toBe(1000);
  });

  test('A4 unknown barcode shows not-found, cart unchanged', async ({ page }) => {
    await scan(page, BARCODE.P1);
    await expect(page.getByTestId('pos-total')).toHaveText('₹250');
    await scan(page, BARCODE.UNKNOWN);
    await expect(page.getByTestId('pos-unknown-barcode')).toBeVisible();
    await expect(page.getByTestId('pos-cart-line')).toHaveCount(1);
    await expect(page.getByTestId('pos-total')).toHaveText('₹250');
  });

  test('A5 khata with no customer attached is blocked, nothing saved', async ({ page, api, seed, retailerToken }) => {
    await scan(page, BARCODE.P1);
    await page.getByTestId('pos-pay-credit').click();
    let checkoutCalls = 0;
    page.on('request', (r) => { if (r.url().includes('/erp/pos-checkout/')) checkoutCalls += 1; });
    await page.getByTestId('pos-complete-bill').click();
    await expect(page.getByText('Customer mobile is required for Credit')).toBeVisible();
    expect(checkoutCalls).toBe(0);
    await expect(page.getByTestId('pos-checkout-complete')).toHaveCount(0);
    expect(await productStock(api, await retailerToken(), seed.products.P1)).toBe(100);
  });

  test('A6 regression: cash bill P3 x1 = 165', async ({ page, api, seed, retailerToken }) => {
    await scan(page, BARCODE.P3);
    await expect(page.getByTestId('pos-total')).toHaveText('₹165');
    await page.getByTestId('pos-pay-cash').click();
    const checkout = posCheckoutResponse(page);
    await page.getByTestId('pos-complete-bill').click();
    const response = await checkout;
    expect(response.status()).toBe(201);
    const { order } = await response.json();
    await expect(page.getByTestId('pos-paid-total')).toHaveText('₹165');
    const saved = await getJson(api, `orders/${order.id}/`, await retailerToken());
    expect(saved.total_amount).toBe('165.00');
    expect(saved.payment_mode).toBe('cash');
    expect(saved.payment_status).toBe('verified');
    expect(await productStock(api, await retailerToken(), seed.products.P3)).toBe(99);
  });
});
