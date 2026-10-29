/**
 * Slice: inventory. Stock in (purchases), stock out (write-offs, orders), low/out-of-stock signals.
 * POS sale stock effects are covered in pos.spec.ts (B1/B4/B5).
 */
import { test, expect, urls } from '../fixtures';
import { addToCart, authed, customerToken, getJson, placeCodOrder, productStock, retailerLogin } from '../helpers';
import { C2_MOBILE as C2_PHONE, PRODUCT } from '../seed';
import { customerProducts, patch, post, retailerProducts, rows } from '../slice-helpers';

const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());

test.describe('@slice-inventory', () => {
  test('purchase bill from a supplier adds stock, sets cost, logs it and books the debt @slice-inventory @retailer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const supplier = await post(api, 'products/erp/suppliers/', r1, { company_name: 'E2EI Agro Traders', contact_person: 'E2EI Ravi', phone_number: '9300000001' });
    await post(api, 'products/erp/purchase-invoices/', r1, {
      supplier: supplier.id, invoice_number: 'E2EI-001', invoice_date: today(), total_amount: '2000.00',
      items: [{ product: seed.products.P1, quantity: 10, purchase_price: '200.00', total: '2000.00' }],
    });
    const product = await getJson(api, `products/${seed.products.P1}/`, r1);
    expect(Number(product.quantity)).toBe(110);
    expect(Number(product.purchase_price)).toBe(200);
    const ledger = rows(await getJson(api, `products/erp/inventory-ledger/?product_id=${seed.products.P1}`, r1));
    expect(ledger.some((l) => /Purchase Inward: Invoice #E2EI-001/.test(l.reason ?? ''))).toBe(true);
    const suppliers = rows(await getJson(api, 'products/erp/suppliers/', r1));
    expect(Number(suppliers.find((s) => s.id === supplier.id)?.balance_due)).toBe(2000);
  });

  test('write-off takes stock out with a reason and refuses unknown reasons @slice-inventory @retailer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const bad = await api.post(`products/${seed.products.P2}/write-off/`, { ...authed(r1), data: { quantity: 3, reason: 'lost-in-transit' } });
    expect(bad.status()).toBe(400);
    expect(await productStock(api, r1, seed.products.P2)).toBe(100);
    const writeOff = await post(api, `products/${seed.products.P2}/write-off/`, r1, { quantity: 3, reason: 'damage' });
    expect(writeOff).toMatchObject({ log_type: 'damaged', new_quantity: '97.000' });
    expect(await productStock(api, r1, seed.products.P2)).toBe(97);
  });

  test('low and out of stock show in stats and filters; customers stop seeing sold-out items @slice-inventory @retailer @customer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await patch(api, `products/${seed.products.P3}/update/`, r1, { quantity: 5 });
    await patch(api, `products/${seed.products.P5}/update/`, r1, { quantity: 0 });
    const stats = await getJson(api, 'products/stats/', r1);
    expect(stats).toMatchObject({ low_stock_products: 1, out_of_stock_products: 1 });
    expect((await retailerProducts(api, r1, 'low_stock=true')).map((p) => p.name)).toEqual([PRODUCT.P3.name]);
    expect((await retailerProducts(api, r1, 'in_stock=false')).map((p) => p.name)).toEqual([PRODUCT.P5.name]);

    const c2 = await customerToken(api, C2_PHONE);
    const visible = (await customerProducts(api, c2, seed.retailers.R1, 'in_stock=true')).map((p) => p.name);
    expect(visible).toContain(PRODUCT.P3.name);
    expect(visible).not.toContain(PRODUCT.P5.name);
  });

  test('cart refuses out-of-stock items and quantities above stock @slice-inventory @customer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await patch(api, `products/${seed.products.P5}/update/`, r1, { quantity: 0 });
    await patch(api, `products/${seed.products.P3}/update/`, r1, { quantity: 5 });
    const c2 = await customerToken(api, C2_PHONE);
    const none = await api.post('cart/add/', { ...authed(c2), data: { product_id: seed.products.P5, quantity: 1 } });
    expect(none.status()).toBe(400);
    expect(await none.text()).toMatch(/Only 0(\.0+)? items available/);
    const many = await api.post('cart/add/', { ...authed(c2), data: { product_id: seed.products.P3, quantity: 6 } });
    expect(many.status()).toBe(400);
    expect(await many.text()).toMatch(/Only 5(\.0+)? items available/);
  });

  test('order cannot be placed when stock ran out after carting @slice-inventory @customer @orders', async ({ api, seed, retailerToken }) => {
    const c2 = await customerToken(api, C2_PHONE);
    await addToCart(api, c2, seed.products.P3, 4);
    const r1 = await retailerToken();
    await patch(api, `products/${seed.products.P3}/update/`, r1, { quantity: 2 });
    const slots = await getJson(api, `retailers/${seed.retailers.R1}/fulfillment-slots/?delivery_mode=delivery`, c2);
    const response = await api.post('orders/place/', {
      ...authed(c2),
      data: { retailer_id: String(seed.retailers.R1), address_id: seed.c2_address, delivery_mode: 'delivery', payment_mode: 'cash', special_instructions: '', use_reward_points: false, coupon_code: null, fulfillment_slot_start: slots.slots[0].slot_start },
    });
    expect(response.status(), await response.text()).toBe(400);
    expect(await productStock(api, r1, seed.products.P3)).toBe(2);
  });

  test('placing an order takes stock out; cancelling puts it back @slice-inventory @customer @retailer @orders', async ({ api, seed, retailerToken }) => {
    const c2 = await customerToken(api, C2_PHONE);
    await addToCart(api, c2, seed.products.P2, 4);
    const order = await placeCodOrder(api, c2, seed.retailers.R1, seed.c2_address);
    const r1 = await retailerToken();
    expect(await productStock(api, r1, seed.products.P2)).toBe(96);
    const confirm = await api.patch(`orders/${order.id}/status/`, { ...authed(r1), data: { status: 'confirmed' } });
    expect(confirm.status(), await confirm.text()).toBe(200);
    expect(await productStock(api, r1, seed.products.P2)).toBe(96); // taken once, at placement
    const cancel = await api.patch(`orders/${order.id}/status/`, { ...authed(r1), data: { status: 'cancelled', cancellation_reason: 'E2EI out of delivery range' } });
    expect(cancel.status(), await cancel.text()).toBe(200);
    expect(await productStock(api, r1, seed.products.P2)).toBe(100);
  });

  test('retailer records a purchase bill in the UI and stock, cost and supplier balance update @slice-inventory @retailer', async ({ page, api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await post(api, 'products/erp/suppliers/', r1, { company_name: 'E2EI Dal Mill', contact_person: 'E2EI Mohan', phone_number: '9300000002' });
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/purchases/new`);
    await page.getByRole('button', { name: 'Select Supplier' }).click();
    await page.getByText('E2EI Dal Mill').last().click();
    await page.getByPlaceholder('e.g. BILL-4952').fill('E2EI-UI-1');
    const search = page.getByPlaceholder('Scan barcode (F1) or type product name...');
    await search.fill(PRODUCT.P2.barcode);
    await search.press('Enter');
    const row = page.locator('tbody tr').filter({ hasText: PRODUCT.P2.name });
    await expect(row).toHaveCount(1);
    const inputs = row.locator('input');
    await inputs.nth(0).fill('12');
    await inputs.nth(1).fill('110');
    const saved = page.waitForResponse((r) => r.url().includes('/erp/purchase-invoices/') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Save Purchase Bill' }).click();
    const response = await saved;
    expect(response.status(), await response.text()).toBe(201);

    const product = await getJson(api, `products/${seed.products.P2}/`, r1);
    expect(Number(product.quantity)).toBe(112);
    expect(Number(product.purchase_price)).toBe(110);
    const supplier = rows(await getJson(api, 'products/erp/suppliers/', r1)).find((s) => s.company_name === 'E2EI Dal Mill');
    expect(Number(supplier?.balance_due)).toBe(1320);

    await page.goto(`${urls.retailer}/dashboard/suppliers`);
    await expect(page.getByRole('row', { name: /E2EI Dal Mill/ })).toContainText('1,320');
  });

  test('retailer dashboard low and out of stock filters list the right products @slice-inventory @retailer', async ({ page, api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await patch(api, `products/${seed.products.P1}/update/`, r1, { quantity: 3 });
    await patch(api, `products/${seed.products.P4}/update/`, r1, { quantity: 7 });
    await patch(api, `products/${seed.products.P5}/update/`, r1, { quantity: 0 });
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/products`);
    // Summary cards show "Filters" (no counts), so assert the filtered rows instead.
    const main = page.getByRole('main');
    await page.getByRole('button', { name: 'Low Stock (<=10)' }).click();
    await expect(main.getByText('Biscuit pack').first()).toBeVisible();
    await expect(main.getByText('Atta 5kg').first()).toBeVisible();
    await expect(main.getByText('Sunflower Oil 1L')).toHaveCount(0);
    await page.getByRole('button', { name: 'Out of Stock', exact: true }).click();
    await expect(main.getByText('Ghee 500g').first()).toBeVisible();
    await expect(main.getByText('Biscuit pack')).toHaveCount(0);
  });
});
