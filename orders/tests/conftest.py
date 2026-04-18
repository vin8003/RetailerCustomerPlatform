import pytest
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework.throttling import BaseThrottle
from authentication.models import User
from retailers.models import RetailerProfile
from products.models import Product, ProductCategory, ProductBrand
from customers.models import CustomerProfile, CustomerAddress
from orders.models import Order, OrderItem
from cart.models import Cart, CartItem

# Globally disable throttling for tests
BaseThrottle.allow_request = lambda self, request, view: True


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer():
    user = User.objects.create_user(
        username="order_customer",
        email="order_customer@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
        is_email_verified=True,
    )
    CustomerProfile.objects.create(user=user)
    return user


@pytest.fixture
def retailer_user():
    user = User.objects.create_user(
        username="order_retailer",
        email="order_retailer@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    return user


@pytest.fixture
def retailer(retailer_user):
    return RetailerProfile.objects.create(
        user=retailer_user,
        shop_name="Order Test Shop",
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
    return ProductCategory.objects.create(name="Order Category", retailer=retailer)


@pytest.fixture
def brand():
    return ProductBrand.objects.create(name="Order Brand")


@pytest.fixture
def product(retailer, category, brand):
    return Product.objects.create(
        retailer=retailer,
        name="Order Product",
        category=category,
        brand=brand,
        price=Decimal("100.00"),
        quantity=50,
        track_inventory=True,
        is_active=True,
        is_available=True,
        minimum_order_quantity=1,
        maximum_order_quantity=10,
        unit="piece",
    )


@pytest.fixture
def product2(retailer, category, brand):
    return Product.objects.create(
        retailer=retailer,
        name="Order Product 2",
        category=category,
        brand=brand,
        price=Decimal("50.00"),
        quantity=20,
        track_inventory=True,
        is_active=True,
        is_available=True,
        minimum_order_quantity=1,
        unit="piece",
    )


@pytest.fixture
def address(customer):
    return CustomerAddress.objects.create(
        customer=customer,
        title="Home",
        address_type="home",
        address_line1="456 Test St",
        city="TestCity",
        state="TestState",
        pincode="123456",
        is_default=True,
    )


@pytest.fixture
def cart_with_items(customer, retailer, product, product2):
    cart = Cart.objects.create(customer=customer, retailer=retailer)
    CartItem.objects.create(cart=cart, product=product, quantity=2, unit_price=product.price)
    CartItem.objects.create(cart=cart, product=product2, quantity=1, unit_price=product2.price)
    return cart


@pytest.fixture
def order(customer, retailer, address, product):
    o = Order.objects.create(
        customer=customer,
        retailer=retailer,
        delivery_address=address,
        delivery_mode="delivery",
        payment_mode="cash",
        subtotal=Decimal("200.00"),
        total_amount=Decimal("200.00"),
        status="pending",
    )
    OrderItem.objects.create(
        order=o,
        product=product,
        product_name=product.name,
        product_price=product.price,
        product_unit=product.unit,
        quantity=2,
        unit_price=product.price,
        total_price=Decimal("200.00"),
    )
    return o
