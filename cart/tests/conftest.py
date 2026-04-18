import pytest
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework.throttling import BaseThrottle
from authentication.models import User
from retailers.models import RetailerProfile
from products.models import Product, ProductCategory, ProductBrand
from cart.models import Cart, CartItem

# Globally disable throttling for tests
BaseThrottle.allow_request = lambda self, request, view: True


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer():
    user = User.objects.create_user(
        username="cart_customer",
        email="cart_customer@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
        is_email_verified=True,
    )
    return user


@pytest.fixture
def retailer_user():
    user = User.objects.create_user(
        username="cart_retailer",
        email="cart_retailer@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    return user


@pytest.fixture
def retailer(retailer_user):
    return RetailerProfile.objects.create(
        user=retailer_user,
        shop_name="Test Shop",
        address_line1="123 Main St",
        city="TestCity",
        state="TestState",
        pincode="123456",
        is_active=True,
        offers_delivery=True,
        offers_pickup=True,
        minimum_order_amount=Decimal("50.00"),
    )


@pytest.fixture
def category(retailer):
    return ProductCategory.objects.create(
        name="Test Category",
        retailer=retailer,
    )


@pytest.fixture
def brand():
    return ProductBrand.objects.create(name="Test Brand")


@pytest.fixture
def product(retailer, category, brand):
    return Product.objects.create(
        retailer=retailer,
        name="Test Product",
        category=category,
        brand=brand,
        price=Decimal("100.00"),
        quantity=50,
        track_inventory=True,
        is_active=True,
        is_available=True,
        minimum_order_quantity=1,
        maximum_order_quantity=10,
    )


@pytest.fixture
def product2(retailer, category, brand):
    return Product.objects.create(
        retailer=retailer,
        name="Test Product 2",
        category=category,
        brand=brand,
        price=Decimal("200.00"),
        quantity=20,
        track_inventory=True,
        is_active=True,
        is_available=True,
        minimum_order_quantity=1,
    )


@pytest.fixture
def cart(customer, retailer):
    return Cart.objects.create(customer=customer, retailer=retailer)


@pytest.fixture
def cart_item(cart, product):
    return CartItem.objects.create(
        cart=cart,
        product=product,
        quantity=2,
        unit_price=product.price,
    )
