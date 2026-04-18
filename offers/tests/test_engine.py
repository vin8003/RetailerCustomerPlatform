import pytest
from decimal import Decimal
from unittest.mock import MagicMock
from offers.models import Offer, OfferTarget
from offers.engine import OfferEngine
from products.models import ProductCategory, ProductBrand

class DummyCartItem:
    def __init__(self, product, quantity, unit_price):
        self.product = product
        self.quantity = quantity
        self.unit_price = Decimal(str(unit_price))
        self.total_price = self.unit_price * quantity
        self.id = product.id # For item_discounts mapping

@pytest.fixture
def engine():
    return OfferEngine()

@pytest.mark.django_db
class TestOfferEngine:
    
    def test_percentage_discount(self, engine, retailer, product):
        # 10% off
        offer = Offer.objects.create(
            retailer=retailer, name="10% Off", offer_type="percentage",
            value=Decimal("10.00"), is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")
        
        cart_items = [DummyCartItem(product, 2, 100)] # 200 total
        result = engine.calculate_offers(cart_items, retailer)
        
        assert result['total_savings'] == Decimal("20.00")
        assert result['discounted_total'] == Decimal("180.00")
        assert len(result['applied_offers']) == 1

    def test_flat_amount_discount(self, engine, retailer, product):
        # Flat ₹50 off per item
        offer = Offer.objects.create(
            retailer=retailer, name="₹50 Off", offer_type="flat_amount",
            value=Decimal("50.00"), is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")
        
        cart_items = [DummyCartItem(product, 2, 200)] # 400 total
        result = engine.calculate_offers(cart_items, retailer)
        
        # 50 * 2 = 100 savings
        assert result['total_savings'] == Decimal("100.00")
        assert result['discounted_total'] == Decimal("300.00")

    def test_cart_value_discount(self, engine, retailer, product):
        # ₹100 off on orders above ₹500
        offer = Offer.objects.create(
            retailer=retailer, name="Big Saver", offer_type="cart_value",
            value=Decimal("100.00"), value_type="amount", min_order_value=Decimal("500.00"),
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")
        
        # Test below threshold
        cart_low = [DummyCartItem(product, 2, 100)] # 200
        res_low = engine.calculate_offers(cart_low, retailer)
        assert res_low['total_savings'] == 0
        
        # Test above threshold
        cart_high = [DummyCartItem(product, 6, 100)] # 600
        res_high = engine.calculate_offers(cart_high, retailer)
        assert res_high['total_savings'] == Decimal("100.00")

    def test_bxgy_mixed_cheapest_free(self, engine, retailer, product, product_factory):
        # Buy 2 Get 1 Free
        offer = Offer.objects.create(
            retailer=retailer, name="Buy 2 Get 1", offer_type="bxgy",
            buy_quantity=2, get_quantity=1, is_cheapest_free=True,
            is_active=True, bxgy_strategy='mixed', value=0
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")
        
        p_expensive = product # price=10 (from conftest usually)
        p_cheap = product_factory.create(retailer=retailer, price=Decimal("5.00"))
        
        # Cart: 2 expensive, 1 cheap. Total 3 items. 1 should be free (the cheap one).
        cart_items = [
            DummyCartItem(p_expensive, 2, 10),
            DummyCartItem(p_cheap, 1, 5)
        ]
        
        result = engine.calculate_offers(cart_items, retailer)
        assert result['total_savings'] == Decimal("5.00")
        assert result['discounted_total'] == Decimal("20.00")

    def test_bxgy_same_product(self, engine, retailer, product):
        # Buy 1 Get 1 Free (Same Product)
        offer = Offer.objects.create(
            retailer=retailer, name="BOGO", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0
        )
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)
        
        # 3 items of same product. Buy 1 get 1 means 1 set applied, 1 paid full.
        # Actually 1 free per 2 units. So 1 free out of 3.
        cart_items = [DummyCartItem(product, 3, 100)]
        result = engine.calculate_offers(cart_items, retailer)
        assert result['total_savings'] == Decimal("100.00")

    def test_stacking_logic(self, engine, retailer, product):
        # Offer 1: 10% Off (Non-stackable)
        off1 = Offer.objects.create(
            retailer=retailer, name="Exclusive 10%", offer_type="percentage",
            value=Decimal("10.00"), is_active=True, is_stackable=False, priority=10
        )
        OfferTarget.objects.create(offer=off1, target_type="all_products")
        
        # Offer 2: ₹5 Off (Stackable but won't apply to Exclusive item)
        off2 = Offer.objects.create(
            retailer=retailer, name="Stackable ₹5", offer_type="flat_amount",
            value=Decimal("5.00"), is_active=True, is_stackable=True, priority=5
        )
        OfferTarget.objects.create(offer=off2, target_type="all_products")
        
        cart_items = [DummyCartItem(product, 1, 100)]
        result = engine.calculate_offers(cart_items, retailer)
        
        # Only 10% should apply because it's higher priority and exclusive
        assert result['total_savings'] == Decimal("10.00")
        assert len(result['applied_offers']) == 1
        assert result['applied_offers'][0]['name'] == "Exclusive 10%"

    def test_exclusion_logic(self, engine, retailer, product, product_factory):
        # Offer: 50% Off except Product 2
        offer = Offer.objects.create(
            retailer=retailer, name="Selective 50%", offer_type="percentage",
            value=Decimal("50.00"), is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products", is_excluded=False)
        
        p_excluded = product_factory.create(retailer=retailer)
        OfferTarget.objects.create(offer=offer, target_type="product", product=p_excluded, is_excluded=True)
        
        cart_items = [
            DummyCartItem(product, 1, 100),
            DummyCartItem(p_excluded, 1, 100)
        ]
        
        result = engine.calculate_offers(cart_items, retailer)
        # Should only discount 'product', not 'p_excluded'
        assert result['total_savings'] == Decimal("50.00")

    def test_loyalty_points_benefit(self, engine, retailer, product):
        # Offer: 10% Cashback (Points)
        offer = Offer.objects.create(
            retailer=retailer, name="10% Cashback", offer_type="percentage",
            value=Decimal("10.00"), benefit_type="credit_points", is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")
        
        cart_items = [DummyCartItem(product, 1, 100)]
        result = engine.calculate_offers(cart_items, retailer)
        
        assert result['total_savings'] == 0 # Price doesn't change
        assert result['total_points'] == Decimal("10.00")
        assert result['applied_offers'][0]['benefit_type'] == 'credit_points'

    def test_cart_value_percentage_with_cap(self, engine, retailer, product):
        # 10% off on > ₹500, max ₹50
        offer = Offer.objects.create(
            retailer=retailer, name="Capped Discount", offer_type="cart_value",
            value=Decimal("10.00"), value_type="percent", min_order_value=Decimal("500.00"),
            max_discount_amount=Decimal("50.00"), is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")
        
        cart_items = [DummyCartItem(product, 10, 100)] # 1000 total. 10% is 100. Capped at 50.
        result = engine.calculate_offers(cart_items, retailer)
        assert result['total_savings'] == Decimal("50.00")

    def test_category_and_brand_targets(self, engine, retailer, category, brand, product_factory):
        # Offer for specific Category and Brand
        other_cat = ProductCategory.objects.create(retailer=retailer, name="Other")
        p_match_cat = product_factory.create(name="P1", category=category, brand=ProductBrand.objects.create(name="OtherBrand"), price=100)
        p_match_brand = product_factory.create(name="P2", category=other_cat, brand=brand, price=100)
        
        offer = Offer.objects.create(
            retailer=retailer, name="Cat or Brand Offer", offer_type="percentage",
            value=Decimal("50.00"), is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type="category", category=category)
        OfferTarget.objects.create(offer=offer, target_type="brand", brand=brand)
        
        cart_items = [
            DummyCartItem(p_match_cat, 1, 100),
            DummyCartItem(p_match_brand, 1, 100)
        ]
        
        result = engine.calculate_offers(cart_items, retailer)
        # Should match both (OR logic)
        assert result['total_savings'] == Decimal("100.00")

