/**
 * Slice: offers and coupons. Every check reads the customer cart the engine priced.
 * Open bugs are test.fixme with a bug annotation; E2E_RUN_FIXME=1 runs them anyway.
 */
import { test, expect, urls } from '../fixtures';
import { addToCart, authed, createOffer, customerCart, customerToken, getJson, retailerLogin } from '../helpers';
import { C2_MOBILE as C2_PHONE } from '../seed';
import { applyCoupon, bug, customerAtShop, patch } from '../slice-helpers';

const fixme = process.env.E2E_RUN_FIXME ? test : test.fixme;
const istDate = (n: number) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date(Date.now() + n * 24 * 3600 * 1000));
const days = (n: number) => new Date(Date.now() + n * 24 * 3600 * 1000).toISOString();

test.describe('@slice-offers', () => {
  test('percentage offer on one product discounts only that line @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'E2EO 10% oil', offer_type: 'percentage', value_type: 'percent', value: '10.00' }, seed.products.P3);
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P3, 2); // 330
    await addToCart(api, token, seed.products.P2, 1); // 140, not targeted
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(470);
    expect(cart.discounted_total).toBe(437);
    expect(cart.total_savings).toBe(33);
    expect(cart.applied_offers.map((o: { name: string }) => o.name)).toEqual(['E2EO 10% oil']);
  });

  test('flat amount offer comes off every unit (intended) @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'E2EO ₹20 off ghee', offer_type: 'flat_amount', value_type: 'amount', value: '20.00' }, seed.products.P5);
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P5, 3);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(300);
    expect(cart.discounted_total).toBe(240);
  });

  test('buy 2 get 1 on the same product makes every third unit free @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), {
      name: 'E2EO biscuits 2+1', offer_type: 'bxgy', value_type: 'amount', value: '0', bxgy_strategy: 'same_product', buy_quantity: 2, get_quantity: 1,
    }, seed.products.P4);
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P4, 3);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(90);
    expect(cart.total_savings).toBe(30);
    expect(cart.discounted_total).toBe(60);
  });

  test('cart value offer waits for its minimum order @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'E2EO ₹50 over 500', offer_type: 'cart_value', value_type: 'amount', value: '50.00', min_order_value: '500.00' });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 1); // 250
    let cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.discounted_total).toBe(250);
    expect(cart.applied_offers).toHaveLength(0);
    await addToCart(api, token, seed.products.P1, 1); // 500
    cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.subtotal).toBe(500);
    expect(cart.discounted_total).toBe(450);
  });

  test('expired, future and inactive offers do not apply @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await createOffer(api, r1, { name: 'E2EO expired', offer_type: 'percentage', value_type: 'percent', value: '10.00', start_date: days(-10), end_date: days(-1) }, seed.products.P1);
    await createOffer(api, r1, { name: 'E2EO future', offer_type: 'percentage', value_type: 'percent', value: '10.00', start_date: days(2), end_date: days(9) }, seed.products.P1);
    await createOffer(api, r1, { name: 'E2EO paused', offer_type: 'percentage', value_type: 'percent', value: '10.00', is_active: false }, seed.products.P1);
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 2);
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_offers).toHaveLength(0);
    expect(cart.discounted_total).toBe(500);
  });

  test('two non-stackable cart offers: only the higher-priority one applies @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await createOffer(api, r1, { name: 'E2EO 10% cart', offer_type: 'cart_value', value_type: 'percent', value: '10.00', priority: 1 });
    await createOffer(api, r1, { name: 'E2EO ₹80 cart', offer_type: 'cart_value', value_type: 'amount', value: '80.00', priority: 5 });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 2); // 500: 10% = ₹50, flat = ₹80
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_offers.map((o: { name: string }) => o.name)).toEqual(['E2EO ₹80 cart']);
    expect(cart.total_savings).toBe(80);
    expect(cart.discounted_total).toBe(420);
  });

  fixme('two non-stackable cart offers at equal priority: the bigger saving wins @slice-offers @customer @offers',
    bug('https://vin8003.atlassian.net/browse/OE-388: equal priority, 10% (₹50) vs ₹80 on a ₹500 cart applies the 10% offer (total ₹450); expected ₹80 off, total ₹420'),
    async ({ api, seed, retailerToken }) => {
      const r1 = await retailerToken();
      await createOffer(api, r1, { name: 'E2EO 10% cart', offer_type: 'cart_value', value_type: 'percent', value: '10.00' });
      await createOffer(api, r1, { name: 'E2EO ₹80 cart', offer_type: 'cart_value', value_type: 'amount', value: '80.00' });
      const token = await customerToken(api, C2_PHONE);
      await addToCart(api, token, seed.products.P1, 2);
      const cart = await customerCart(api, token, seed.retailers.R1);
      expect(cart.applied_offers.map((o: { name: string }) => o.name)).toEqual(['E2EO ₹80 cart']);
      expect(cart.discounted_total).toBe(420);
    });

  test('cart value offer: ₹0.01 below the minimum is not applied, exactly at it is @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    const offer = await createOffer(api, r1, { name: 'E2EO edge', offer_type: 'cart_value', value_type: 'amount', value: '50.00', min_order_value: '500.01' });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 2); // exactly 500.00
    let cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_offers).toHaveLength(0);
    expect(cart.discounted_total).toBe(500);
    await patch(api, `offers/${offer.id}/`, r1, { min_order_value: '500.00' });
    cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_offers.map((o: { name: string }) => o.name)).toEqual(['E2EO edge']);
    expect(cart.discounted_total).toBe(450);
  });

  fixme('percentage cap lowers the price, not only the offer label @slice-offers @customer @offers',
    bug('OE-385: 10% capped at ₹20 on P3×2 (₹330) reports ₹20 saved but the cart total is ₹297.00 (₹33 off); expected ₹310.00'),
    async ({ api, seed, retailerToken }) => {
      await createOffer(api, await retailerToken(), { name: 'E2EO 10% cap 20', offer_type: 'percentage', value_type: 'percent', value: '10.00', max_discount_amount: '20.00' }, seed.products.P3);
      const token = await customerToken(api, C2_PHONE);
      await addToCart(api, token, seed.products.P3, 2);
      const cart = await customerCart(api, token, seed.retailers.R1);
      expect(cart.applied_offers[0].savings).toBe(20);
      expect(cart.total_savings).toBe(20);
      expect(cart.discounted_total).toBe(310);
    });

  test('stackable cart offer skips a line a non-stackable product offer already discounted @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await createOffer(api, r1, { name: 'E2EO ₹10 ghee', offer_type: 'flat_amount', value_type: 'amount', value: '10.00' }, seed.products.P5);
    await createOffer(api, r1, { name: 'E2EO 5% stack', offer_type: 'cart_value', value_type: 'percent', value: '5.00', is_stackable: true });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P5, 2);
    await addToCart(api, token, seed.products.P2, 1);
    const cart = await customerCart(api, token, seed.retailers.R1);
    // Intended: a non-stackable product offer marks its line exclusive, and cart offers skip exclusive lines (5% applies to P2 only).
    expect(cart.subtotal).toBe(340);
    expect(cart.discounted_total).toBe(313);
  });

  fixme('tiered price and flat price offers the API accepts actually change the price @slice-offers @customer @offers',
    bug('OE-375: The offers API accepts offer_type tiered_price and flat_price (201) but the engine has no branch for them: P4×6 with "₹25 each from 5" and P5×2 with "flat ₹80" give no discount'),
    async ({ api, seed, retailerToken }) => {
      const r1 = await retailerToken();
      await createOffer(api, r1, { name: 'E2EO tier 25', offer_type: 'tiered_price', value_type: 'amount', value: '25.00', tiered_min_quantity: '5' }, seed.products.P4);
      await createOffer(api, r1, { name: 'E2EO ghee at 80', offer_type: 'flat_price', value_type: 'amount', value: '80.00' }, seed.products.P5);
      const token = await customerToken(api, C2_PHONE);
      await addToCart(api, token, seed.products.P4, 6);
      await addToCart(api, token, seed.products.P5, 2);
      const cart = await customerCart(api, token, seed.retailers.R1);
      expect(cart.discounted_total).toBe(6 * 25 + 2 * 80);
    });

  test('coupon: code is case-insensitive, discounts the cart, and can be removed @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'E2EO coupon 15%', offer_type: 'cart_value', value_type: 'percent', value: '15.00', coupon_code: 'E2EO15', is_public: false });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 2); // 500
    expect((await customerCart(api, token, seed.retailers.R1)).discounted_total).toBe(500); // coupon offers are never automatic
    const apply = await applyCoupon(api, token, seed.retailers.R1, 'e2eo15');
    expect(apply.status(), await apply.text()).toBe(200);
    let cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_coupon.code).toBe('E2EO15');
    expect(cart.discounted_total).toBe(425);
    const remove = await api.post('cart/remove-coupon/', { ...authed(token), data: { retailer_id: seed.retailers.R1 } });
    expect(remove.status(), await remove.text()).toBe(200);
    cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_coupon).toBeNull();
    expect(cart.discounted_total).toBe(500);
  });

  test('coupon: unknown, expired and below-minimum codes are refused with a reason @slice-offers @customer @offers', async ({ api, seed, retailerToken }) => {
    const r1 = await retailerToken();
    await createOffer(api, r1, { name: 'E2EO old coupon', offer_type: 'cart_value', value_type: 'amount', value: '20.00', coupon_code: 'E2EOOLD', start_date: days(-10), end_date: days(-1) });
    await createOffer(api, r1, { name: 'E2EO min 500', offer_type: 'cart_value', value_type: 'amount', value: '50.00', coupon_code: 'E2EOMIN', min_order_value: '500.00' });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P4, 2); // 60
    const cases: [string, RegExp][] = [['E2EONOPE', /invalid coupon/i], ['E2EOOLD', /expired/i], ['E2EOMIN', /₹440\.00 more/]];
    for (const [code, message] of cases) {
      const response = await applyCoupon(api, token, seed.retailers.R1, code);
      expect(response.status(), code).toBe(400);
      expect((await response.json()).error, code).toMatch(message);
    }
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.applied_coupon).toBeNull();
    expect(cart.discounted_total).toBe(60);
  });

  test('cart page: invalid coupon shows the reason, valid coupon shows the saving @slice-offers @customer @offers', async ({ page, api, seed, retailerToken }) => {
    await createOffer(api, await retailerToken(), { name: 'E2EO ₹40 coupon', offer_type: 'cart_value', value_type: 'amount', value: '40.00', coupon_code: 'E2EO40', is_public: false });
    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P1, 1);
    await customerAtShop(page, C2_PHONE, seed.retailers.R1);
    await page.goto(`${urls.customer}/cart`);
    const input = page.getByPlaceholder('Enter coupon code');
    await input.fill('E2EONOPE');
    await page.getByRole('button', { name: 'Apply', exact: true }).click();
    await expect(page.getByText('Invalid coupon code').first()).toBeVisible();
    await input.fill('E2EO40');
    await page.getByRole('button', { name: 'Apply', exact: true }).click();
    await expect(page.getByText('-₹40.00', { exact: true }).first()).toBeVisible();
    expect((await customerCart(api, token, seed.retailers.R1)).discounted_total).toBe(210);
  });

  test('retailer creates a capped percentage offer in the UI and the customer cart gets it @slice-offers @retailer @customer @offers', async ({ page, api, seed, retailerToken }) => {
    await retailerLogin(page);
    await page.goto(`${urls.retailer}/dashboard/offers/new`);
    await page.getByLabel('Offer Name').fill('E2EO UI 20% off');
    await page.locator('input[name="value"]').fill('20');
    await page.locator('input[name="max_discount_amount"]').fill('100');
    await page.locator('input[name="end_date"]').fill(istDate(7));
    const created = page.waitForResponse((r) => /\/api\/offers\/$/.test(r.url()) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create Offer' }).click();
    const createdResponse = await created;
    expect(createdResponse.status(), await createdResponse.text()).toBe(201);
    await page.waitForURL('**/dashboard/offers**');
    await expect(page.getByText('E2EO UI 20% off').first()).toBeVisible();

    const offers = await getJson(api, 'offers/', await retailerToken());
    const offer = (Array.isArray(offers) ? offers : offers.results).find((o: { name: string }) => o.name === 'E2EO UI 20% off');
    expect(offer).toMatchObject({ offer_type: 'percentage', value: '20.00', max_discount_amount: '100.00', is_active: true });

    const token = await customerToken(api, C2_PHONE);
    await addToCart(api, token, seed.products.P2, 2); // 280 -> 20% = 56, under the cap
    const cart = await customerCart(api, token, seed.retailers.R1);
    expect(cart.discounted_total).toBe(224);
  });

  fixme('retailer can save an offer with no end date from the UI @slice-offers @retailer @offers',
    bug('OE-376: Offers > Create New Offer with End Date left blank: Create Offer gets 400 {"end_date":["Datetime has wrong format..."]} and an alert; the form sends end_date "" instead of null, so open-ended offers cannot be made in the UI'),
    async ({ page, api, retailerToken }) => {
      await retailerLogin(page);
      await page.goto(`${urls.retailer}/dashboard/offers/new`);
      await page.getByLabel('Offer Name').fill('E2EO no end date');
      await page.locator('input[name="value"]').fill('5');
      page.on('dialog', (d) => d.dismiss());
      const created = page.waitForResponse((r) => /\/api\/offers\/$/.test(r.url()) && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Create Offer' }).click();
      expect((await created).status()).toBe(201);
      const offers = await getJson(api, 'offers/', await retailerToken());
      const offer = (Array.isArray(offers) ? offers : offers.results).find((o: { name: string }) => o.name === 'E2EO no end date');
      expect(offer?.end_date).toBeNull();
    });
});
