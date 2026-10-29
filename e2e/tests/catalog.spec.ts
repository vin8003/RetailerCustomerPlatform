/**
 * Slice: catalog and products. Retailer-side changes are checked where the customer sees them.
 */
import { test, expect, urls } from '../fixtures';
import { addToCart, authed, customerToken, getJson, placeCodOrder, retailerLogin } from '../helpers';
import { C2_MOBILE as C2_PHONE, PRODUCT } from '../seed';
import { createProduct, customerAtShop, customerProducts, patch, post, retailerProducts, rows } from '../slice-helpers';

// 1x1 PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==', 'base64');
const names = (list: Record<string, any>[]) => list.map((p) => p.name).sort();

test.describe('@slice-catalog', () => {
  test('new product with a category and group shows in retailer search and customer filters @slice-catalog @retailer @customer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const category = await post(api, 'products/categories/create/', r1, { name: 'E2EC Snacks' });
    const product = await createProduct(api, r1, {
      name: 'E2EC Namkeen 200g', price: '45.00', quantity: 20, barcode: '8900000099011', category: category.id, product_group: 'E2EC Namkeen',
    });
    expect(product).toMatchObject({ name: 'E2EC Namkeen 200g', price: '45.00' });
    expect(Number(product.quantity)).toBe(20);

    expect(names(await retailerProducts(api, r1, 'search=Namkeen'))).toEqual(['E2EC Namkeen 200g']);
    expect(names(await retailerProducts(api, r1, `category=${category.id}`))).toEqual(['E2EC Namkeen 200g']);
    expect(names(await retailerProducts(api, r1, 'search=8900000099011'))).toEqual(['E2EC Namkeen 200g']);

    const c2 = await customerToken(api, C2_PHONE);
    const R1 = seed.retailers.R1;
    expect(names(await customerProducts(api, c2, R1, `category=${category.id}`))).toEqual(['E2EC Namkeen 200g']);
    expect(names(await customerProducts(api, c2, R1, `product_group=${encodeURIComponent('E2EC Namkeen')}`))).toEqual(['E2EC Namkeen 200g']);
    const categories = rows(await getJson(api, `products/retailer/${R1}/categories/`, c2));
    expect(categories.find((c) => c.name === 'E2EC Snacks')?.product_count).toBe(1);
    const groups = await getJson(api, 'products/product-groups/', r1);
    expect(groups).toContain('E2EC Namkeen');
  });

  test('a second product with the same barcode is refused @slice-catalog @retailer', async ({ api, retailerToken }) => {
    const r1 = await retailerToken();
    const response = await api.post('products/create/', { ...authed(r1), data: { name: 'E2EC Copycat', price: '10', quantity: 1, unit: 'piece', barcode: PRODUCT.P1.barcode } });
    expect(response.status()).toBe(400);
    expect(await retailerProducts(api, r1, 'search=E2EC%20Copycat')).toHaveLength(0);
  });

  test('customer price filters, search and price ordering @slice-catalog @customer', async ({ api, seed }) => {
    const c2 = await customerToken(api, C2_PHONE);
    const R1 = seed.retailers.R1;
    expect(names(await customerProducts(api, c2, R1, 'min_price=100&max_price=150'))).toEqual(['Ghee 500g', 'Toor Dal 1kg']);
    expect(names(await customerProducts(api, c2, R1, 'search=dal'))).toEqual(['Toor Dal 1kg']);
    const byPrice = (await customerProducts(api, c2, R1, 'ordering=price')).map((p) => Number(p.price));
    expect(byPrice).toEqual([30, 100, 140, 165, 250]);
  });

  test('editing price and archiving reach the customer; reactivating brings it back @slice-catalog @retailer @customer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const c2 = await customerToken(api, C2_PHONE);
    const R1 = seed.retailers.R1;
    const P2 = seed.products.P2;
    await patch(api, `products/${P2}/update/`, r1, { price: '150.00', name: 'Toor Dal 1kg Premium' });
    const detail = await getJson(api, `products/retailer/${R1}/${P2}/`, c2);
    expect(detail).toMatchObject({ name: 'Toor Dal 1kg Premium', price: '150.00' });

    await patch(api, `products/${P2}/update/`, r1, { is_active: false });
    expect(await customerProducts(api, c2, R1, 'search=Toor')).toHaveLength(0);
    expect(names(await retailerProducts(api, r1, 'search=Toor&is_active=false'))).toEqual(['Toor Dal 1kg Premium']);

    await patch(api, `products/${P2}/update/`, r1, { is_active: true });
    expect(names(await customerProducts(api, c2, R1, 'search=Toor'))).toEqual(['Toor Dal 1kg Premium']);
  });

  test('deleting a product hides it from customers and the cart refuses it @slice-catalog @retailer @customer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const c2 = await customerToken(api, C2_PHONE);
    const response = await api.delete(`products/${seed.products.P4}/delete/`, authed(r1));
    expect(response.status(), await response.text()).toBe(200);
    expect(await customerProducts(api, c2, seed.retailers.R1, 'search=Biscuit')).toHaveLength(0);
    expect(names(await customerProducts(api, c2, seed.retailers.R1, ''))).not.toContain('Biscuit pack');
    const add = await api.post('cart/add/', { ...authed(c2), data: { product_id: seed.products.P4, quantity: 1 } });
    expect(add.status()).toBe(400);
    expect(await add.json()).toEqual({ product_id: ['Product not found or not available'] });
  });

  test('deleting a product that has an order keeps the order and its line intact @slice-catalog @retailer @customer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const c2 = await customerToken(api, C2_PHONE);
    await addToCart(api, c2, seed.products.P3, 2);
    const order = await placeCodOrder(api, c2, seed.retailers.R1, seed.c2_address);
    const response = await api.delete(`products/${seed.products.P3}/delete/`, authed(r1));
    expect(response.status(), await response.text()).toBe(200);
    expect(await response.json()).toEqual({ message: 'Product deleted successfully' });
    // Delete is soft: the order still reads back with the same line and totals.
    const after = await getJson(api, `orders/${order.id}/`, r1);
    expect(after.subtotal).toBe('330.00');
    expect(after.items).toHaveLength(1);
    expect(after.items[0]).toMatchObject({ product: seed.products.P3, product_name: 'Sunflower Oil 1L', total_price: 330 });
    expect(await customerProducts(api, c2, seed.retailers.R1, 'search=Sunflower')).toHaveLength(0);
  });

  test('product image upload rejects a file that is not an image @slice-catalog @retailer', async ({ api, retailerToken }) => {
    const response = await api.post('products/create/', {
      headers: { Authorization: `Bearer ${await retailerToken()}` },
      multipart: { name: 'E2EC Bad Image', price: '10', quantity: '1', unit: 'piece', image: { name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('not an image') } },
    });
    expect(response.status()).toBe(400);
    expect(await response.json()).toEqual({ image: ['Upload a valid image. The file you uploaded was either not an image or a corrupted image.'] });
  });

  test('category rename and delete @slice-catalog @retailer @customer', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const category = await post(api, 'products/categories/create/', r1, { name: 'E2EC Pulses' });
    await patch(api, `products/${seed.products.P2}/update/`, r1, { category: category.id });
    const renamed = await api.patch(`products/categories/${category.id}/update/`, { ...authed(r1), data: { name: 'E2EC Dals' } });
    expect(renamed.status(), await renamed.text()).toBe(200);
    const c2 = await customerToken(api, C2_PHONE);
    const listed = rows(await getJson(api, `products/retailer/${seed.retailers.R1}/categories/`, c2));
    expect(listed.find((c) => c.id === category.id)).toMatchObject({ name: 'E2EC Dals', product_count: 1 });

    const refused = await api.delete(`products/categories/${category.id}/delete/`, authed(r1));
    expect(refused.status()).toBe(400);
    expect((await refused.json()).error).toMatch(/assigned to existing products/);
    await patch(api, `products/${seed.products.P2}/update/`, r1, { category: null });
    const removed = await api.delete(`products/categories/${category.id}/delete/`, authed(r1));
    expect(removed.status(), await removed.text()).toBe(200);
    const after = rows(await getJson(api, `products/retailer/${seed.retailers.R1}/categories/`, c2));
    expect(after.find((c) => c.id === category.id)).toBeUndefined();
  });

  test('pack linked to a master bulk product takes its stock from the master @slice-catalog @retailer', async ({ api, retailerToken }) => {
    const r1 = await retailerToken();
    const master = await createProduct(api, r1, { name: 'E2EC Rice 25kg bag', price: '1000.00', quantity: 4, unit: 'kg', is_parent_bulk: true });
    const pack = await createProduct(api, r1, { name: 'E2EC Rice 5kg pack', price: '220.00', quantity: 0, unit: 'kg', parent_bulk_product: master.id, conversion_factor: '5' });
    expect(Number((await getJson(api, `products/${pack.id}/`, r1)).quantity)).toBe(0.8);
    await patch(api, `products/${master.id}/update/`, r1, { quantity: 10 });
    expect(Number((await getJson(api, `products/${pack.id}/`, r1)).quantity)).toBe(2);
  });

  test('retailer adds a product with an image in the UI; customer finds it and opens its page @slice-catalog @retailer @customer', async ({ page, browser, api, seed, retailerToken }) => {
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/products/add`);
    await page.locator('input[type="file"]').first().setInputFiles({ name: 'e2ec.png', mimeType: 'image/png', buffer: PNG });
    await page.getByLabel('Product Name *').fill('E2EC Jaggery 1kg');
    await page.getByLabel('Selling Price (₹) *').fill('85');
    await page.getByLabel('Stock Quantity *').fill('12');
    await page.getByPlaceholder('e.g. Ketchup & Sauces').fill('E2EC Sweeteners');
    const created = page.waitForResponse((r) => r.url().includes('/products/create/') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create Product' }).click();
    const response = await created;
    expect(response.status(), await response.text()).toBe(201);

    const [product] = await retailerProducts(api, await retailerToken(), 'search=Jaggery');
    expect(product).toMatchObject({ name: 'E2EC Jaggery 1kg', price: '85.00', quantity: 12 });
    // The uploaded PNG is stored re-encoded as JPEG, so the saved URL ends in .jpg.
    expect(String(product.image_url ?? product.image)).toMatch(/\/media\/uploads\/product\/.+\.jpg$/);

    const customer = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
    await customerAtShop(customer, C2_PHONE, seed.retailers.R1);
    await customer.goto(`${urls.customer}/retailer/products?retailerId=${seed.retailers.R1}&search=Jaggery`);
    await expect(customer.getByRole('heading', { name: 'E2EC Jaggery 1kg' })).toBeVisible();
    await expect(customer.getByText('1 item')).toBeVisible();
    await customer.getByRole('heading', { name: 'E2EC Jaggery 1kg' }).click();
    await customer.waitForURL('**/retailer/product?**');
    await expect(customer.getByRole('heading', { name: 'E2EC Jaggery 1kg', level: 1 })).toBeVisible();
    await expect(customer.getByText('₹85').first()).toBeVisible();
    await customer.context().close();
  });

  test('retailer product list: search box and stock tabs filter the table @slice-catalog @retailer', async ({ page, api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await patch(api, `products/${seed.products.P3}/update/`, r1, { quantity: 4 });
    await patch(api, `products/${seed.products.P5}/update/`, r1, { quantity: 0 });
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/products`);
    const table = page.getByRole('main');
    await expect(table.getByText('Atta 5kg').first()).toBeVisible();

    await page.getByPlaceholder('Search products by name, barcode, or category...').fill('Sunflower');
    await expect(table.getByText('Sunflower Oil 1L').first()).toBeVisible();
    await expect(table.getByText('Atta 5kg')).toHaveCount(0);
    await page.getByPlaceholder('Search products by name, barcode, or category...').fill('');

    await page.getByRole('button', { name: 'Low Stock (<=10)' }).click();
    await expect(table.getByText('Sunflower Oil 1L').first()).toBeVisible();
    await expect(table.getByText('Atta 5kg')).toHaveCount(0);
    await expect(table.getByText('Ghee 500g')).toHaveCount(0);

    await page.getByRole('button', { name: 'Out of Stock', exact: true }).click();
    await expect(table.getByText('Ghee 500g').first()).toBeVisible();
    await expect(table.getByText('Sunflower Oil 1L')).toHaveCount(0);
  });
});
