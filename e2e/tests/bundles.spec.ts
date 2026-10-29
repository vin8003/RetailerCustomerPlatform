/**
 * Slice bundles: "SFB Soap Bundle x3" (₹80) is a pack of 3 x "SFB Soap Bar" (₹30, 60 in stock).
 * OrderEasy models it with pack sizing (parent_bulk_product + conversion_factor 3): the bundle has no stock
 * of its own; selling one draws 3 soaps, and the bundle's stock is soap stock / 3.
 * (There is no multi-SKU kit feature, e.g. rice + soap in one bundle; see the slice report.)
 */
import { test, expect, urls } from '../fixtures';
import { customerLogin, customerToken, customerUseSeedCity, getJson, posCheckoutResponse, retailerLogin } from '../helpers';
import { PASSWORD } from '../env';
import { cartLine, expectLineQty, scan } from '../pos';
import { SFB_CUSTOMER_MOBILE, SFB_PRODUCT, SFB_RETAILER, sfbIds, sfbRetailerToken, stock } from '../sfb';

const SOAP_STOCK = Number(SFB_PRODUCT.SOAP.stock); // 60
const UNITS = Number(SFB_PRODUCT.SOAP3.units); // 3

test.describe('Slice bundles - pack-of-3 bundle on POS and customer app', { tag: ['@slice-bundles'] }, () => {
  test('BU1 POS: 2 bundles bill at ₹160 and draw 6 soaps', { tag: ['@retailer', '@pos'] }, async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    const token = await sfbRetailerToken(api, PASSWORD);
    expect(await stock(api, token, ids.products.SOAP3)).toBe(SOAP_STOCK / UNITS);

    await retailerLogin(page, SFB_RETAILER.username);
    await page.goto(`${urls.retailer}/dashboard/pos`);
    await expect(page.getByText(SFB_PRODUCT.SOAP3.name).first()).toBeVisible();
    await scan(page, SFB_PRODUCT.SOAP3.barcode);
    await expectLineQty(page, SFB_PRODUCT.SOAP3.barcode, 1);
    await scan(page, SFB_PRODUCT.SOAP3.barcode);
    await expectLineQty(page, SFB_PRODUCT.SOAP3.barcode, 2);
    await expect(cartLine(page, SFB_PRODUCT.SOAP3.barcode)).toContainText(SFB_PRODUCT.SOAP3.name);
    await expect(page.getByTestId('pos-total')).toHaveText('₹160');

    await page.getByTestId('pos-pay-cash').click();
    const checkout = posCheckoutResponse(page);
    await page.getByTestId('pos-complete-bill').click();
    const response = await checkout;
    expect(response.status(), await response.text()).toBe(201);
    const { order } = await response.json();
    await expect(page.getByTestId('pos-paid-total')).toHaveText('₹160');

    const saved = await getJson(api, `orders/${order.id}/`, token);
    expect(Number(saved.total_amount)).toBe(160);
    expect(saved.items.map((i: { product: number; quantity: number }) => [i.product, Number(i.quantity)]))
      .toEqual([[ids.products.SOAP3, 2]]);
    expect(await stock(api, token, ids.products.SOAP)).toBe(SOAP_STOCK - 2 * UNITS);
    expect(await stock(api, token, ids.products.SOAP3)).toBe((SOAP_STOCK - 2 * UNITS) / UNITS);
  });

  test('BU2 customer: 2 bundles order at ₹80 each and reserve 6 soaps', { tag: ['@customer'] }, async ({ page, api, seed }) => {
    const ids = sfbIds(seed);
    const retailerToken = await sfbRetailerToken(api, PASSWORD);
    await customerUseSeedCity(page);
    await customerLogin(page, SFB_CUSTOMER_MOBILE);
    await page.goto(`${urls.customer}/retailers`);
    await page.getByText(SFB_RETAILER.shop_name).first().click();
    await page.waitForURL('**/retailer?id=*');
    await page.getByTestId(`add-to-cart-${ids.products.SOAP3}`).first().click();
    await page.getByTestId(`cart-increment-${ids.products.SOAP3}`).first().click();
    await expect(page.getByTestId(`cart-qty-${ids.products.SOAP3}`).first()).toHaveText('2');

    await page.goto(`${urls.customer}/cart`);
    await page.getByTestId('cart-checkout').click();
    await page.waitForURL('**/checkout**');
    await page.getByTestId('slot-picker-open').click();
    await page.getByTestId('slot-option').first().click();
    await page.getByTestId('slot-confirm').click();
    await page.getByTestId(`checkout-address-${ids.addresses.NEAR}`).click();
    await page.getByTestId('checkout-pay-cod').click();
    // ₹160 of bundles + ₹20 delivery (NEAR, 1 km).
    await expect(page.getByTestId('checkout-total')).toHaveText('₹180.00');
    const placed = page.waitForResponse((r) => r.url().includes('/orders/place/') && r.request().method() === 'POST');
    await page.getByTestId('checkout-place-order').click();
    const response = await placed;
    expect(response.status(), await response.text()).toBe(201);
    await page.waitForURL('**/orders/detail?id=*');
    const orderId = Number(new URL(page.url()).searchParams.get('id'));

    const order = await getJson(api, `orders/${orderId}/`, await customerToken(api, SFB_CUSTOMER_MOBILE));
    expect(Number(order.total_amount)).toBe(180);
    expect(order.items.map((i: { product: number; quantity: number; product_price: number }) =>
      [i.product, Number(i.quantity), Number(i.product_price)])).toEqual([[ids.products.SOAP3, 2, 80]]);
    expect(await stock(api, retailerToken, ids.products.SOAP)).toBe(SOAP_STOCK - 2 * UNITS);
    expect(await stock(api, retailerToken, ids.products.SOAP3)).toBe((SOAP_STOCK - 2 * UNITS) / UNITS);
  });

  test('BU3 customer cannot order more bundles than soap stock covers', { tag: ['@customer'] }, async ({ api, seed }) => {
    const ids = sfbIds(seed);
    const token = await customerToken(api, SFB_CUSTOMER_MOBILE);
    const tooMany = SOAP_STOCK / UNITS + 1; // 21 bundles = 63 soaps > 60
    const response = await api.post('cart/add/', { headers: { Authorization: `Bearer ${token}` }, data: { product_id: ids.products.SOAP3, quantity: tooMany } });
    expect(response.status(), await response.text()).toBe(400);
    expect(await stock(api, await sfbRetailerToken(api, PASSWORD), ids.products.SOAP)).toBe(SOAP_STOCK);
  });
});
