import pytest
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework.throttling import BaseThrottle
from authentication.models import User
from retailers.models import RetailerProfile
from products.models import (
from products.models import (
    Product, ProductCategory, ProductBrand, ProductReview,
    ProductInventoryLog, MasterProduct, SearchTelemetry,
)
from customers.models import (
    CustomerProfile, CustomerWishlist, CustomerAddress, 
    CustomerNotification, CustomerLoyalty, LoyolaTransaction
)
from offers.models import Offer, OfferTarget
from retailers.models import (
    RetailerProfile, RetailerOperatingHours, RetailerRewardConfig,
    RetailerCategory, RetailerReview
)

# Globally disable throttling for tests
BaseThrottle.allow_request = lambda self, request, view: True


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer():
    user = User.objects.create_user(
        username="prod_customer",
        email="prod_customer@test.com",
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
        username="prod_retailer",
        email="prod_retailer@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    return user


@pytest.fixture
def retailer(retailer_user):
    return RetailerProfile.objects.create(
        user=retailer_user,
        shop_name="Products Test Shop",
        address_line1="123 Main St",
        city="TestCity",
        state="TestState",
        pincode="123456",
        is_active=True,
    )


@pytest.fixture
def category(retailer):
    return ProductCategory.objects.create(name="Groceries", retailer=retailer)


@pytest.fixture
def subcategory(retailer, category):
    return ProductCategory.objects.create(
        name="Snacks", retailer=retailer, parent=category
    )


@pytest.fixture
def brand():
    return ProductBrand.objects.create(name="TestBrand")


@pytest.fixture
def product(retailer, category, brand):
    return Product.objects.create(
        retailer=retailer,
        name="Test Rice 5kg",
        category=category,
        brand=brand,
        price=Decimal("90.00"),
        original_price=Decimal("100.00"),
        quantity=50,
        track_inventory=True,
        is_active=True,
        is_available=True,
        is_featured=True,
        minimum_order_quantity=1,
        maximum_order_quantity=10,
        unit="kg",
    )


@pytest.fixture
def product2(retailer, category, brand):
    return Product.objects.create(
        retailer=retailer,
        name="Test Wheat Flour",
        category=category,
        brand=brand,
        price=Decimal("50.00"),
        quantity=30,
        track_inventory=True,
        is_active=True,
        is_available=True,
        minimum_order_quantity=1,
        unit="kg",
    )


@pytest.fixture
def master_product():
    return MasterProduct.objects.create(
        barcode="8901234567890",
        name="Master Rice Product",
        mrp=Decimal("120.00"),
    )


@pytest.fixture
def offer(retailer, product):
    off = Offer.objects.create(
        retailer=retailer,
        name="Rice Discount",
        offer_type="percentage",
        value=Decimal("10.00"),
        is_active=True,
    )
    OfferTarget.objects.create(
        offer=off,
        target_type="product",
        product=product,
    )
    return off


@pytest.fixture
def wishlist_item(customer, product):
    return CustomerWishlist.objects.create(customer=customer, product=product)


@pytest.fixture
def address(customer):
    return CustomerAddress.objects.create(
        customer=customer,
        title="Home",
        address_line1="456 Oak Lane",
        city="TestCity",
        state="TestState",
        pincode="123456",
        is_default=True
    )


@pytest.fixture
def address2(customer):
    return CustomerAddress.objects.create(
        customer=customer,
        title="Office",
        address_line1="789 Work St",
        city="WorkCity",
        state="WorkState",
        pincode="654321",
        is_default=False
    )


@pytest.fixture
def operating_hours(retailer):
    return RetailerOperatingHours.objects.create(
        retailer=retailer,
        day_of_week="monday",
        is_open=True,
        opening_time="09:00:00",
        closing_time="18:00:00"
    )


@pytest.fixture
def reward_config(retailer):
    return RetailerRewardConfig.objects.get_or_create(retailer=retailer)[0]


@pytest.fixture
def retailer_category():
    return RetailerCategory.objects.create(name="Pharmacy")


@pytest.fixture
def notification(customer):
    return CustomerNotification.objects.create(
        customer=customer,
        notification_type="system",
        title="Test Title",
        message="Test Message"
    )

