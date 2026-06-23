import pytest
import time
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from cart.models import Cart, CartItem
from offers.models import Offer, OfferTarget, OfferRedemption
from offers.engine import OfferEngine
from products.models import Product
from orders.models import Order, OrderItem

class DummyCartItem:
    def __init__(self, product, quantity, unit_price):
        self.product = product
        self.quantity = quantity
        self.unit_price = Decimal(str(unit_price))
        self.total_price = self.unit_price * quantity
        self.id = product.id

@pytest.mark.django_db
class TestCartBXGYRefactoredFailing:

    def test_cart_db_quantity_remains_unmutated_under_bxgy(self, api_client, customer, retailer, product):
        """
        FAILING TEST: Verify that the backend NEVER forcefully changes customer entered quantity
        in the database, and only OfferEngine returns dynamic free quantities.
        """
        api_client.force_authenticate(user=customer)
        
        # Create Buy 1 Get 1 Free offer (Same Product strategy)
        offer = Offer.objects.create(
            retailer=retailer, name="BOGO Same Product", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)

        # 1. Customer adds 1 unit of product-A to cart
        url_add = reverse('add_to_cart')
        response = api_client.post(url_add, {'product_id': product.id, 'quantity': 1})
        assert response.status_code == status.HTTP_201_CREATED

        # Database quantity MUST remain exactly 1 (No forceful mutation!)
        cart_item = CartItem.objects.get(product=product, cart__customer=customer)
        assert cart_item.quantity == 1

        # 2. Customer updates quantity to 3 (wants to buy 3, which gets 3 free, so 6 total)
        url_update = reverse('update_cart_item', kwargs={'item_id': cart_item.id})
        response = api_client.put(url_update, {'quantity': 3})
        assert response.status_code == status.HTTP_200_OK

        # Database quantity MUST remain exactly 3 (No forceful mutation!)
        cart_item.refresh_from_db()
        assert cart_item.quantity == 3

    def test_bxgy_engine_performance_scaling(self, retailer, product):
        """
        FAILING TEST: Verify OfferEngine calculates BXGY mathematically in O(1) time
        without running massive loops that freeze on high quantities.
        """
        engine = OfferEngine()
        offer = Offer.objects.create(
            retailer=retailer, name="BOGO same product B2B", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)

        # B2B large quantity
        cart_items = [DummyCartItem(product, 5000, 100)]

        start_time = time.time()
        result = engine.calculate_offers(cart_items, retailer)
        end_time = time.time()

        elapsed = end_time - start_time
        # Must complete in less than 50 milliseconds (O(1) calculation)
        assert elapsed < 0.05

    def test_checkout_validation_uses_discounted_total(self, api_client, customer, retailer, product):
        """
        FAILING TEST: Verify validate_cart and get_cart_summary evaluate minimum order amount
        against the discounted total after offer engine calculation, to prevent desync during checkout.
        """
        api_client.force_authenticate(user=customer)
        
        # Retailer minimum order amount is ₹150
        retailer.minimum_order_amount = Decimal("150.00")
        retailer.save()

        # Create 50% Off Offer
        offer = Offer.objects.create(
            retailer=retailer, name="Half Price", offer_type="percentage",
            value=Decimal("50.00"), is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        # Cart item: 2 units at ₹80 each = ₹160 gross total.
        # Discounted total is ₹80, which is below the ₹150 minimum order threshold.
        cart, _ = Cart.objects.get_or_create(customer=customer, retailer=retailer)
        CartItem.objects.create(cart=cart, product=product, quantity=2, unit_price=80)

        # Cart summary should show that we CANNOT checkout
        url_summary = reverse('get_cart_summary') + f"?retailer_id={retailer.id}"
        response = api_client.get(url_summary)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['can_checkout'] is False

        # Validate cart should return False
        url_validate = reverse('validate_cart')
        response = api_client.post(url_validate, {'retailer_id': retailer.id})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['valid'] is False

    def test_pos_order_creation_with_offers_engine(self, api_client, retailer_user, retailer, product):
        """
        FAILING TEST: Verify POS checkout uses OfferEngine with POS applicability,
        correctly creates OfferRedemptions, and reduces correct inventory (including free items).
        """
        api_client.force_authenticate(user=retailer_user)
        
        # Create POS-applicable Buy 1 Get 1 Free offer
        offer = Offer.objects.create(
            retailer=retailer, name="BOGO POS", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0,
            applicable_on='pos' # POS only!
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)

        product.quantity = 100
        product.track_inventory = True
        product.save()

        # Create POS order for 4 units (Buy 2 Get 2 free)
        url_pos = reverse('create_pos_order')
        data = {
            'items': [{'product_id': product.id, 'quantity': 4, 'unit_price': float(product.price)}],
            'payment_mode': 'cash',
            'subtotal': float(product.price * 4),
            'discount_amount': 0, # Should be calculated by engine
            'total_amount': float(product.price * 2)
        }

        response = api_client.post(url_pos, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED

        # 1. Verification of inventory reduction (2 purchased + 2 free = 4 total)
        product.refresh_from_db()
        assert product.quantity == 96

        # 2. Verification of order items created (1 item with quantity 4 and effective unit price)
        order = Order.objects.latest('created_at')
        order_item = OrderItem.objects.get(order=order, product=product)
        assert order_item.quantity == 4
        assert order_item.unit_price == product.price / 2

        # 3. Verification of OfferRedemption tracking
        redemptions = OfferRedemption.objects.filter(order=order, offer=offer)
        assert redemptions.exists()

    def test_pos_order_split_payment_with_offers(self, api_client, retailer_user, retailer, product):
        """
        EDGE CASE: Verify POS order creation works with split payments (cash + credit)
        when discounts are computed, validating payments against the discounted total.
        """
        api_client.force_authenticate(user=retailer_user)
        # Clear out existing offers to prevent interference from conftest fixtures
        Offer.objects.all().delete()

        # Create 10% Off POS-applicable offer
        offer = Offer.objects.create(
            retailer=retailer, name="10% POS Discount", offer_type="percentage",
            value=Decimal("10.00"), is_active=True, applicable_on='both'
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        # 2 items at product.price (100.00 each) = ₹200 subtotal.
        # 10% discount = ₹20.00. Total = ₹180.00.
        subtotal = float(product.price * 2)
        total_amount = float((product.price * 2) * Decimal("0.90"))

        # Shadow customer for credit tracking
        from django.contrib.auth import get_user_model
        User = get_user_model()
        shadow_customer = User.objects.create(
            username="shadow_credit_test",
            phone_number="9876543210",
            registration_status='shadow',
            user_type='customer'
        )
        from retailers.models import RetailerCustomerMapping
        RetailerCustomerMapping.objects.create(
            retailer=retailer, customer=shadow_customer, credit_limit=500
        )

        url_pos = reverse('create_pos_order')
        data = {
            'items': [{'product_id': product.id, 'quantity': 2, 'unit_price': float(product.price)}],
            'payment_mode': 'split',
            'subtotal': subtotal,
            'discount_amount': 0,
            'total_amount': total_amount,
            'customer_mobile': '9876543210',
            'payment_details': {
                'cash': 100.0,
                'credit': 80.0,  # Cash (100) + Credit (80) = 180 total
            }
        }

        response = api_client.post(url_pos, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED

        order = Order.objects.latest('created_at')
        assert order.payment_mode == 'split'
        assert order.cash_amount == Decimal("100.00")
        assert order.credit_amount == Decimal("80.00")
        assert order.total_amount == Decimal("180.00")

    def test_pos_vs_mobile_applicability_channel_isolation(self, api_client, customer, retailer_user, retailer, product):
        """
        EDGE CASE: Verify POS-only offers are not applied on Mobile (customer app),
        and Mobile-only offers are not applied on POS checkout.
        """
        # Clear out existing offers to prevent interference from conftest fixtures
        Offer.objects.all().delete()

        # 1. Create a POS-only offer
        pos_offer = Offer.objects.create(
            retailer=retailer, name="POS Exclusive BOGO", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0, applicable_on='pos'
        )
        OfferTarget.objects.create(offer=pos_offer, target_type="product", product=product)

        # 2. Create a Mobile-only offer
        mobile_offer = Offer.objects.create(
            retailer=retailer, name="App Exclusive 50% Off", offer_type="percentage",
            value=Decimal("50.00"), is_active=True, applicable_on='mobile'
        )
        OfferTarget.objects.create(offer=mobile_offer, target_type="all_products")

        # --- MOBILE CHANNEL CHECK ---
        # Add 1 unit of product to mobile cart, call get_cart.
        # Mobile cart should get the 50% offer, but NOT the BOGO same_product offer!
        api_client.force_authenticate(user=customer)
        cart, _ = Cart.objects.get_or_create(customer=customer, retailer=retailer)
        CartItem.objects.create(cart=cart, product=product, quantity=1)

        url_get = reverse('get_cart') + f"?retailer_id={retailer.id}"
        response_mobile = api_client.get(url_get)
        assert response_mobile.status_code == status.HTTP_200_OK

        # 50% Mobile-only offer should reduce unit price from 100.00 to 50.00
        discounts_mobile = response_mobile.data['item_discounts']
        assert discounts_mobile[cart.items.first().id]['final_price'] == 50.00
        # POS-only BOGO should NOT have mutated display quantity to 2
        assert discounts_mobile[cart.items.first().id]['total_display_quantity'] == 1

        # --- POS CHANNEL CHECK ---
        # Call POS checkout with 1 unit of product.
        # POS order should get BOGO (meaning it gets 2 items total, effective unit price 50.00),
        # but should NOT get the 50% App Exclusive discount (which would make price 25.00!).
        api_client.force_authenticate(user=retailer_user)
        url_pos = reverse('create_pos_order')
        data = {
            'items': [{'product_id': product.id, 'quantity': 2, 'unit_price': float(product.price)}],
            'payment_mode': 'cash',
            'subtotal': float(product.price * 2),
            'discount_amount': 0,
            'total_amount': float(product.price)
        }
        response_pos = api_client.post(url_pos, data, format='json')
        assert response_pos.status_code == status.HTTP_201_CREATED

        order = Order.objects.latest('created_at')
        order_item = OrderItem.objects.get(order=order, product=product)
        # BOGO POS applied: qty 2, price 50.00.
        # 50% mobile discount not applied: if it did, unit_price would be 25.00.
        assert order_item.quantity == 2
        assert order_item.unit_price == Decimal("50.00")

    def test_checkout_validation_fractional_quantities(self, api_client, customer, retailer, category, brand):
        """
        EDGE CASE: Verify checkout validation works flawlessly when products support fractional
        quantities (e.g. loose sugar 1.5kg) and checks them accurately against limits and stock.
        """
        api_client.force_authenticate(user=customer)

        # Create product with fractional quantities allowed
        fractional_product = Product.objects.create(
            retailer=retailer, name="Loose Sugar", category=category, brand=brand,
            price=Decimal("40.00"), quantity=Decimal("1.200"), track_inventory=True,
            minimum_order_quantity=Decimal("0.500"), maximum_order_quantity=Decimal("2.000"),
            unit="kg", is_active=True, is_available=True
        )

        cart, _ = Cart.objects.get_or_create(customer=customer, retailer=retailer)
        
        # Add 1.500 kg to cart (exceeds stock of 1.200 kg)
        CartItem.objects.create(cart=cart, product=fractional_product, quantity=Decimal("1.500"))

        url_validate = reverse('validate_cart')
        response = api_client.post(url_validate, {'retailer_id': retailer.id})
        # Validation should fail due to stock limit
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "only 1.200" in response.data['errors'][0].lower()

    def test_stock_validation_uses_total_display_quantity_for_bxgy(self, api_client, customer, retailer, product):
        """
        EDGE CASE: Verify validate_cart checks the dynamic total_display_quantity (purchased + free)
        against available stock, preventing checkout if the free items exceed available stock.
        """
        api_client.force_authenticate(user=customer)
        # Clear out existing offers to prevent interference from conftest fixtures
        Offer.objects.all().delete()

        # Product stock is exactly 5
        product.quantity = Decimal("5.000")
        product.track_inventory = True
        product.save()

        # Create Same-product BOGO (Buy 1 Get 1 free)
        offer = Offer.objects.create(
            retailer=retailer, name="BOGO Same Product", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)

        # Customer adds 6 units to cart (with BOGO, group size is 2, so 6 total)
        cart, _ = Cart.objects.get_or_create(customer=customer, retailer=retailer)
        CartItem.objects.create(cart=cart, product=product, quantity=6)

        # Validate cart should fail because 6 units are needed, but only 5 are in stock
        url_validate = reverse('validate_cart')
        response = api_client.post(url_validate, {'retailer_id': retailer.id})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['valid'] is False
        assert "only 5.000" in response.data['errors'][0].lower()

    def test_min_order_value_with_same_product_bxgy(self, api_client, customer, retailer, product):
        """
        EDGE CASE: Verify that minimum order amount is evaluated against the POST-DISCOUNT total
        under a same-product BOGO. Even if the gross total (including free items) is above the
        threshold, if the discounted (purchased) total is below it, checkout is blocked.
        """
        api_client.force_authenticate(user=customer)
        Offer.objects.all().delete()

        # Retailer minimum order amount is ₹150
        retailer.minimum_order_amount = Decimal("150.00")
        retailer.save()

        # Create BOGO Same Product
        offer = Offer.objects.create(
            retailer=retailer, name="BOGO Same Product", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)

        # Product price is ₹100. Customer adds 1 unit to cart.
        # With BOGO, display total quantity is 2 (Gross total = ₹200, but Discounted total = ₹100).
        # Discounted total ₹100 is less than ₹150 minimum.
        cart, _ = Cart.objects.get_or_create(customer=customer, retailer=retailer)
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=100)

        # Cart summary should show can_checkout is False
        url_summary = reverse('get_cart_summary') + f"?retailer_id={retailer.id}"
        response = api_client.get(url_summary)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['can_checkout'] is False

        # Validate cart should return False
        url_validate = reverse('validate_cart')
        response = api_client.post(url_validate, {'retailer_id': retailer.id})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['valid'] is False

    def test_pos_anonymous_walk_in_checkout(self, api_client, retailer_user, retailer, product):
        """
        EDGE CASE: Verify POS order checkout works flawlessly for anonymous walk-in customers
        where no mobile number or name is shared, and correctly applies POS offers.
        """
        api_client.force_authenticate(user=retailer_user)
        Offer.objects.all().delete()

        # Create POS-applicable BOGO
        offer = Offer.objects.create(
            retailer=retailer, name="POS BOGO", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0, applicable_on='pos'
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)

        product.quantity = 10
        product.track_inventory = True
        product.save()

        # POST POS order without customer_mobile or customer_name
        url_pos = reverse('create_pos_order')
        data = {
            'items': [{'product_id': product.id, 'quantity': 2, 'unit_price': float(product.price)}],
            'payment_mode': 'cash',
            'subtotal': float(product.price * 2),
            'discount_amount': 0,
            'total_amount': float(product.price)
        }

        response = api_client.post(url_pos, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED

        order = Order.objects.latest('created_at')
        assert order.customer is None
        assert order.guest_name in [None, ""]
        assert order.guest_mobile in [None, ""]

        # Verify BOGO applied correctly (1 purchased + 1 free = 2 total)
        order_item = OrderItem.objects.get(order=order, product=product)
        assert order_item.quantity == 2
        assert order_item.unit_price == product.price / 2

        # Verify OfferRedemption is created without customer (customer=None)
        redemptions = OfferRedemption.objects.filter(order=order, offer=offer)
        assert redemptions.exists()
        assert redemptions.first().customer is None

    def test_bxgy_partial_group_distribution(self, retailer, product):
        """
        FAILING TEST: Verify that a partial group correctly calculates free items
        for the remainder. Under Buy 2 Get 2, scanning 3 items should give 1 free item.
        """
        engine = OfferEngine()
        offer = Offer.objects.create(
            retailer=retailer, name="Buy 2 Get 2", offer_type="bxgy",
            buy_quantity=2, get_quantity=2, is_active=True,
            bxgy_strategy='same_product', value=0
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)

        # Total scanned quantity = 3. Under Buy 2 Get 2, group size is 4.
        # full_groups = 3 // 4 = 0
        # remainder = 3 % 4 = 3
        # free_qty = 0 + max(0, 3 - 2) = 1
        cart_items = [DummyCartItem(product, 3, 100)]
        result = engine.calculate_offers(cart_items, retailer)
        
        assert result['total_savings'] == Decimal("100.00")

