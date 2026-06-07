import pytest
from decimal import Decimal
from cart.models import Cart, CartItem, CartSession, CartHistory
from products.models import Product


@pytest.mark.django_db
class TestCartModel:

    def test_cart_str(self, cart):
        assert "Cart -" in str(cart)
        assert "cart_customer" in str(cart)
        assert "Test Shop" in str(cart)

    def test_total_items_empty(self, cart):
        assert cart.total_items == 0

    def test_total_items_with_items(self, cart, product, product2):
        CartItem.objects.create(cart=cart, product=product, quantity=3, unit_price=product.price)
        CartItem.objects.create(cart=cart, product=product2, quantity=2, unit_price=product2.price)
        assert cart.total_items == 5

    def test_total_amount(self, cart, product, product2):
        CartItem.objects.create(cart=cart, product=product, quantity=2, unit_price=Decimal("100.00"))
        CartItem.objects.create(cart=cart, product=product2, quantity=1, unit_price=Decimal("200.00"))
        assert cart.total_amount == Decimal("400.00")

    def test_is_empty(self, cart, product):
        assert cart.is_empty is True
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=product.price)
        assert cart.is_empty is False

    def test_clear(self, cart, product, product2):
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=product.price)
        CartItem.objects.create(cart=cart, product=product2, quantity=1, unit_price=product2.price)
        assert cart.items.count() == 2
        cart.clear()
        assert cart.items.count() == 0

    def test_add_item_new(self, cart, product):
        item = cart.add_item(product, quantity=3)
        assert item.quantity == 3
        assert item.unit_price == product.price
        assert cart.items.count() == 1

    def test_add_item_existing_increments(self, cart, product):
        cart.add_item(product, quantity=2)
        item = cart.add_item(product, quantity=3)
        assert item.quantity == 5

    def test_remove_item_exists(self, cart, product):
        cart.add_item(product, quantity=1)
        result = cart.remove_item(product)
        assert result is True
        assert cart.items.count() == 0

    def test_remove_item_not_exists(self, cart, product2):
        result = cart.remove_item(product2)
        assert result is False

    def test_update_item_quantity(self, cart, product):
        cart.add_item(product, quantity=2)
        result = cart.update_item_quantity(product, 5)
        assert result is True
        assert cart.items.get(product=product).quantity == 5

    def test_update_item_quantity_zero_deletes(self, cart, product):
        cart.add_item(product, quantity=2)
        result = cart.update_item_quantity(product, 0)
        assert result is True
        assert cart.items.count() == 0

    def test_update_item_quantity_not_exists(self, cart, product2):
        result = cart.update_item_quantity(product2, 5)
        assert result is False

    def test_validate_aggregate_stock(self, cart, retailer, category, brand):
        """Test aggregate stock checking on mixed parent and child cart items"""
        # Create a parent product
        parent = Product.objects.create(
            retailer=retailer,
            name="Parent Bulk Product",
            price=Decimal("100.00"),
            quantity=Decimal("10.00"),
            category=category,
            brand=brand,
            is_parent_bulk=True,
            track_inventory=True
        )
        # Create a child product
        child = Product.objects.create(
            retailer=retailer,
            name="Child Product",
            price=Decimal("10.00"),
            quantity=Decimal("100.00"),
            category=category,
            brand=brand,
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.10"),
            track_inventory=True
        )
        
        # Scenario 1: Add 5 parent products (OK, stock is 10)
        is_ok, msg = cart.validate_aggregate_stock(parent, simulate_quantity=Decimal("5.00"))
        assert is_ok is True
        
        # Scenario 2: Add 15 parent products (fails, stock is 10)
        is_ok, msg = cart.validate_aggregate_stock(parent, simulate_quantity=Decimal("15.00"))
        assert is_ok is False
        assert "Total combined cart items require" in msg
        
        # Scenario 3: Add 3 parent products and 30 child products (total 3 + 30*0.1 = 6 parent units, OK)
        cart.add_item(parent, quantity=Decimal("3.00"))
        cart.add_item(child, quantity=Decimal("30.00"))
        is_ok, msg = cart.validate_aggregate_stock(parent)
        assert is_ok is True
        
        # Scenario 4: Add another 2 parent products (simulate_quantity = 5 for parent, total parent units = 5 + 30*0.1 = 8, OK)
        is_ok, msg = cart.validate_aggregate_stock(parent, simulate_quantity=Decimal("5.00"))
        assert is_ok is True
        
        # Scenario 5: Add another 5 parent products (simulate_quantity = 8 for parent, total parent units = 8 + 3 = 11, exceeds)
        is_ok, msg = cart.validate_aggregate_stock(parent, simulate_quantity=Decimal("8.00"))
        assert is_ok is False


@pytest.mark.django_db
class TestCartItemModel:

    def test_cart_item_str(self, cart_item):
        assert "Test Product x 2" == str(cart_item)

    def test_total_price(self, cart_item):
        assert cart_item.total_price == Decimal("200.00")

    def test_is_available(self, cart_item):
        # quantity=2, product has quantity=50 and min=1, max=10
        assert cart_item.is_available is True

    def test_save_sets_unit_price(self, cart, product):
        item = CartItem(cart=cart, product=product, quantity=1)
        item.unit_price = None
        item.save()
        assert item.unit_price == product.price


@pytest.mark.django_db
class TestCartSessionModel:

    def test_cart_session_str(self, retailer):
        session = CartSession.objects.create(
            session_key="abc123",
            retailer=retailer,
            data={"items": []},
        )
        assert str(session) == "Session Cart - abc123"


@pytest.mark.django_db
class TestCartHistoryModel:

    def test_cart_history_str(self, customer, retailer):
        history = CartHistory.objects.create(
            customer=customer,
            retailer=retailer,
            action="add",
        )
        assert "cart_customer" in str(history)
        assert "add" in str(history)
