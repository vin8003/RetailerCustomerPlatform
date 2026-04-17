import pytest
from .factories import ProductFactory, ProductCategoryFactory, MasterProductFactory
from decimal import Decimal

@pytest.mark.django_db
class TestProductLogic:
    def test_pricing_and_discount_calculation(self):
        # original=100, price=80 -> 20% discount
        product = ProductFactory(original_price=Decimal('100.00'), price=Decimal('80.00'))
        
        assert product.discount_percentage == Decimal('20.00')
        assert product.savings == Decimal('20.00')

    def test_increase_reduce_quantity(self):
        product = ProductFactory(quantity=10, track_inventory=True)
        
        # Reduce
        success = product.reduce_quantity(3)
        assert success is True
        assert product.quantity == 7
        
        # Increase
        product.increase_quantity(5)
        assert product.quantity == 12
        
        # Reduce more than available
        success = product.reduce_quantity(20)
        assert success is False
        assert product.quantity == 12

    def test_stock_availability_logic(self):
        # Tracked inventory
        product_tracked = ProductFactory(quantity=5, track_inventory=True, is_available=True)
        assert product_tracked.is_in_stock is True
        
        product_tracked.quantity = 0
        assert product_tracked.is_in_stock is False
        
        # Untracked inventory
        product_untracked = ProductFactory(quantity=0, track_inventory=False, is_available=True)
        assert product_untracked.is_in_stock is True  # Should be True because is_available is True
        
        product_untracked.is_available = False
        assert product_untracked.is_in_stock is False

    def test_can_order_quantity(self):
        product = ProductFactory(
            quantity=10, 
            minimum_order_quantity=2, 
            maximum_order_quantity=5,
            track_inventory=True
        )
        
        assert product.can_order_quantity(1) is False # Below min
        assert product.can_order_quantity(3) is True  # Within range
        assert product.can_order_quantity(6) is False # Above max
        assert product.can_order_quantity(11) is False # Above stock
