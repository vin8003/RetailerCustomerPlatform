import pytest
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from offers.models import Offer, OfferTarget, OfferRedemption
from offers.engine import OfferEngine
from orders.models import Order

class DummyCartItem:
    def __init__(self, product, quantity, unit_price):
        self.product = product
        self.quantity = quantity
        self.unit_price = Decimal(str(unit_price))
        self.total_price = self.unit_price * quantity
        self.id = product.id

@pytest.fixture
def engine():
    return OfferEngine()

@pytest.mark.django_db
class TestCouponSystem:

    def test_coupon_not_applied_automatically(self, engine, retailer, product):
        """Coupon offers should NOT be applied unless coupon_code is passed in context"""
        offer = Offer.objects.create(
            retailer=retailer,
            name="Save 50",
            coupon_code="SAVE50",
            offer_type="cart_value",
            value=Decimal("50.00"),
            value_type="amount",
            min_order_value=Decimal("100.00"),
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        cart_items = [DummyCartItem(product, 2, 100)] # 200 total
        # Call without coupon_code
        result = engine.calculate_offers(cart_items, retailer)
        assert result['total_savings'] == Decimal("0.00")
        assert result['applied_coupon'] is None
        assert len(result['applied_offers']) == 0

    def test_coupon_applied_with_matching_code(self, engine, retailer, product):
        """Coupon offer applies when matching code is supplied"""
        offer = Offer.objects.create(
            retailer=retailer,
            name="Save 50",
            coupon_code="SAVE50",
            offer_type="cart_value",
            value=Decimal("50.00"),
            value_type="amount",
            min_order_value=Decimal("100.00"),
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        cart_items = [DummyCartItem(product, 2, 100)] # 200 total
        context = {'coupon_code': 'save50'} # case-insensitive test
        result = engine.calculate_offers(cart_items, retailer, context=context)

        assert result['total_savings'] == Decimal("50.00")
        assert result['discounted_total'] == Decimal("150.00")
        assert result['applied_coupon'] is not None
        assert result['applied_coupon']['code'] == 'SAVE50'
        assert result['applied_coupon']['savings'] == 50.0

    def test_coupon_loyalty_points(self, engine, retailer, product):
        """Coupon giving loyalty points instead of instant discount"""
        offer = Offer.objects.create(
            retailer=retailer,
            name="Bonus 100 Points",
            coupon_code="BONUS100",
            benefit_type="credit_points",
            offer_type="cart_value",
            value=Decimal("100.00"),
            value_type="amount",
            min_order_value=Decimal("200.00"),
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        cart_items = [DummyCartItem(product, 3, 100)] # 300 total
        context = {'coupon_code': 'BONUS100'}
        result = engine.calculate_offers(cart_items, retailer, context=context)

        # Instant discount should be 0, points earned should be 100
        assert result['total_savings'] == Decimal("0.00")
        assert result['discounted_total'] == Decimal("300.00")
        assert result['total_points'] == Decimal("100.00")
        assert result['applied_coupon'] is not None
        assert result['applied_coupon']['benefit_type'] == 'credit_points'

    def test_coupon_min_order_value_validation(self, engine, retailer, product):
        """Coupon requires min order value"""
        offer = Offer.objects.create(
            retailer=retailer,
            name="High Spender",
            coupon_code="HIGH500",
            offer_type="cart_value",
            value=Decimal("100.00"),
            value_type="amount",
            min_order_value=Decimal("500.00"),
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        cart_items = [DummyCartItem(product, 2, 100)] # 200 total (less than 500)
        context = {'coupon_code': 'HIGH500'}
        result = engine.calculate_offers(cart_items, retailer, context=context)

        assert result['total_savings'] == Decimal("0.00")
        assert result['applied_coupon'] is None
        assert result['coupon_error'] is not None
        assert "Add ₹300.00 more" in result['coupon_error']

    def test_first_time_customer_coupon(self, engine, retailer, product, customer):
        """First time customer coupon fails if customer already has orders"""
        offer = Offer.objects.create(
            retailer=retailer,
            name="Welcome Coupon",
            coupon_code="WELCOME",
            offer_type="cart_value",
            value=Decimal("50.00"),
            value_type="amount",
            target_audience="first_time",
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        cart_items = [DummyCartItem(product, 1, 100)]
        context = {'coupon_code': 'WELCOME', 'customer': customer}

        # User has no orders yet -> should succeed
        result = engine.calculate_offers(cart_items, retailer, context=context)
        assert result['applied_coupon'] is not None

        # Now simulate an existing order for customer
        Order.objects.create(
            order_number="ORD-TEST-1",
            customer=customer,
            retailer=retailer,
            delivery_mode="delivery",
            payment_mode="cash",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="delivered"
        )

        # Now try again -> should fail with first-time error
        result2 = engine.calculate_offers(cart_items, retailer, context=context)
        assert result2['applied_coupon'] is None
        assert result2['coupon_error'] == "This coupon is only valid on your first order"

    def test_get_available_coupons_api(self, api_client, retailer, customer):
        """API should return public coupons and hide secret coupons"""
        from django.urls import reverse
        from rest_framework import status
        
        # Public coupon
        pub = Offer.objects.create(
            retailer=retailer, name="Public 20", coupon_code="PUB20",
            offer_type="percentage", value=Decimal("20.00"), is_public=True, is_active=True
        )
        OfferTarget.objects.create(offer=pub, target_type="all_products")
        
        # Secret coupon
        sec = Offer.objects.create(
            retailer=retailer, name="Secret 50", coupon_code="SECRET50",
            offer_type="percentage", value=Decimal("50.00"), is_public=False, is_active=True
        )
        OfferTarget.objects.create(offer=sec, target_type="all_products")

        api_client.force_authenticate(user=customer)
        url = reverse('available-coupons', kwargs={'retailer_id': retailer.id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        codes = [c['code'] for c in response.data]
        assert "PUB20" in codes
        assert "SECRET50" not in codes

    def test_cart_apply_and_remove_coupon_api(self, api_client, retailer, customer, product):
        """Test POST /api/cart/apply-coupon/ and POST /api/cart/remove-coupon/"""
        from django.urls import reverse
        from rest_framework import status
        from cart.models import Cart, CartItem

        offer = Offer.objects.create(
            retailer=retailer, name="Flat 30 Off", coupon_code="SAVE30",
            offer_type="cart_value", value=Decimal("30.00"), value_type="amount",
            min_order_value=Decimal("50.00"), is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")

        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(cart=cart, product=product, quantity=2, unit_price=Decimal("100.00"))

        api_client.force_authenticate(user=customer)

        # 1. Apply invalid coupon
        url_apply = reverse('cart_apply_coupon')
        res_inv = api_client.post(url_apply, {'retailer_id': retailer.id, 'coupon_code': 'WRONGCODE'}, format='json')
        assert res_inv.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Apply valid coupon
        res_ok = api_client.post(url_apply, {'retailer_id': retailer.id, 'coupon_code': 'save30'}, format='json')
        assert res_ok.status_code == status.HTTP_200_OK
        assert res_ok.data['applied_coupon']['code'] == 'SAVE30'
        assert res_ok.data['total_savings'] == 30.0
        
        # Verify saved in cart model
        cart.refresh_from_db()
        assert cart.applied_coupon_code == 'SAVE30'

        # 3. Remove coupon
        url_remove = reverse('cart_remove_coupon')
        res_rem = api_client.post(url_remove, {'retailer_id': retailer.id}, format='json')
        assert res_rem.status_code == status.HTTP_200_OK
        assert res_rem.data['applied_coupon'] is None
        assert res_rem.data['total_savings'] == 0.0

        cart.refresh_from_db()
        assert cart.applied_coupon_code is None

