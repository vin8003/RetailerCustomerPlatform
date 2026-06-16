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
class TestCartBXGYRefactoredPassing:

    def test_cart_db_quantity_remains_unmutated_under_bxgy(self, api_client, customer, retailer, product):
        """
        Verify that the backend NEVER forcefully changes customer entered quantity
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
        Verify OfferEngine calculates BXGY mathematically in O(1) time
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
        Verify validate_cart and get_cart_summary evaluate minimum order amount
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
        Verify POS checkout uses OfferEngine with POS applicability,
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
