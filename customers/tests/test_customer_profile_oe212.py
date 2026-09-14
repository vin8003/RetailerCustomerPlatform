"""
OE-212 / F-0105 — Customer profile and order history (phone lookup).

Covers: phone → mapping + recent POS/app orders, tenancy, module gate,
query budget. Merge is out of this file (no primitives).
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from customers.models import CustomerProfile
from orders.models import Order, OrderItem
from products.models import Product, ProductBrand, ProductCategory
from retailers.models import OrgModuleFlags, RetailerCustomerMapping, RetailerProfile
from retailers.module_flags_catalog import ERROR_CODE_MODULE_DISABLED
from retailers.organization import ensure_organization_for_profile


def _make_retailer(username, shop_name):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    profile = RetailerProfile.objects.create(
        user=user,
        shop_name=shop_name,
        address_line1="1 Main",
        city="City",
        state="State",
        pincode="110001",
        is_active=True,
    )
    ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_customer(username, phone="9988776655"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        phone_number=phone,
        is_active=True,
        is_phone_verified=True,
        registration_status="registered",
    )
    CustomerProfile.objects.create(user=user)
    return user


def _product(retailer):
    category = ProductCategory.objects.create(name="Cat", retailer=retailer)
    brand = ProductBrand.objects.create(name="Brand")
    return Product.objects.create(
        retailer=retailer,
        name="Widget",
        category=category,
        brand=brand,
        price=Decimal("100.00"),
        quantity=50,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def _order(customer, retailer, product, *, source="app", status_value="delivered", guest_mobile=None, guest_name=None):
    order = Order.objects.create(
        customer=customer,
        retailer=retailer,
        delivery_mode="pickup" if source == "pos" else "delivery",
        payment_mode="cash",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
        status=status_value,
        source=source,
        guest_mobile=guest_mobile,
        guest_name=guest_name,
    )
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        product_price=product.price,
        quantity=1,
        unit_price=product.price,
        total_price=product.price,
    )
    return order


LOOKUP_URL = "lookup_retailer_customer"


@pytest.mark.django_db
class TestPhoneLookupRecentOrders:
    def test_phone_returns_customer_and_pos_plus_app_orders(self, api_client):
        owner, profile = _make_retailer("oe212_owner_ok", "OE212 Shop")
        customer = _make_customer("oe212_cust_ok", phone="9000002101")
        product = _product(profile)
        RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            nickname="Regular",
            current_balance=Decimal("25.00"),
            credit_limit=Decimal("200.00"),
        )
        pos_order = _order(customer, profile, product, source="pos")
        app_order = _order(customer, profile, product, source="app")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "+91 9000002101"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["customer_id"] == customer.id
        assert resp.data["nickname"] == "Regular"
        assert resp.data["phone_number"] == "9000002101"
        assert resp.data["total_orders"] == 2
        assert Decimal(str(resp.data["total_spent"])) == Decimal("200.00")
        assert Decimal(str(resp.data["current_balance"])) == Decimal("25.00")
        sources = {row["source"] for row in resp.data["recent_orders"]}
        assert sources == {"pos", "app"}
        ids = {row["id"] for row in resp.data["recent_orders"]}
        assert ids == {pos_order.id, app_order.id}
        assert all(row["items_count"] == 1 for row in resp.data["recent_orders"])

    def test_recent_orders_capped_at_20(self, api_client):
        owner, profile = _make_retailer("oe212_owner_cap", "OE212 Cap Shop")
        customer = _make_customer("oe212_cust_cap", phone="9000002102")
        product = _product(profile)
        RetailerCustomerMapping.objects.create(retailer=profile, customer=customer)
        for _ in range(22):
            _order(customer, profile, product, source="app")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "9000002102"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["total_orders"] == 22
        assert len(resp.data["recent_orders"]) == 20

    def test_includes_legacy_guest_pos_rows_same_phone(self, api_client):
        owner, profile = _make_retailer("oe212_owner_guest", "OE212 Guest Shop")
        customer = _make_customer("oe212_cust_guest", phone="9000002103")
        product = _product(profile)
        RetailerCustomerMapping.objects.create(retailer=profile, customer=customer)
        _order(customer, profile, product, source="app")
        guest = _order(
            None,
            profile,
            product,
            source="pos",
            guest_mobile="9000002103",
            guest_name="Walk-in",
        )

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "9000002103"})
        assert resp.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in resp.data["recent_orders"]}
        assert guest.id in ids
        assert resp.data["total_orders"] == 2

    def test_guest_only_phone_returns_summary(self, api_client):
        owner, profile = _make_retailer("oe212_owner_gonly", "OE212 Guest Only")
        product = _product(profile)
        _order(
            None,
            profile,
            product,
            source="pos",
            guest_mobile="9000002104",
            guest_name="Counter",
        )

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "9000002104"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["customer_id"] is None
        assert resp.data["registration_status"] == "guest"
        assert resp.data["customer_name"] == "Counter"
        assert len(resp.data["recent_orders"]) == 1

    def test_short_or_missing_phone_is_400(self, api_client):
        owner, _profile = _make_retailer("oe212_owner_400", "OE212 400 Shop")
        api_client.force_authenticate(user=owner)
        missing = api_client.get(reverse(LOOKUP_URL))
        assert missing.status_code == status.HTTP_400_BAD_REQUEST
        short = api_client.get(reverse(LOOKUP_URL), {"phone": "98765"})
        assert short.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_phone_is_404(self, api_client):
        owner, _profile = _make_retailer("oe212_owner_404", "OE212 404 Shop")
        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "9000002199"})
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestPhoneLookupAuthAndTenancy:
    def test_customer_jwt_is_403(self, api_client):
        _owner, profile = _make_retailer("oe212_owner_cust", "OE212 Cust Shop")
        customer = _make_customer("oe212_as_cust", phone="9000002105")
        RetailerCustomerMapping.objects.create(retailer=profile, customer=customer)
        api_client.force_authenticate(user=customer)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "9000002105"})
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "recent_orders" not in resp.data

    def test_disabled_customers_module_is_403(self, api_client):
        owner, profile = _make_retailer("oe212_owner_mod", "OE212 Mod Shop")
        customer = _make_customer("oe212_mod_cust", phone="9000002106")
        RetailerCustomerMapping.objects.create(retailer=profile, customer=customer)
        row = OrgModuleFlags.objects.get(organization=profile.organization)
        flags = dict(row.flags or {})
        flags["customers"] = False
        row.flags = flags
        row.save(update_fields=["flags", "updated_at"])

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "9000002106"})
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
        assert "recent_orders" not in resp.data

    def test_cross_tenant_phone_is_404(self, api_client):
        owner_a, profile_a = _make_retailer("oe212_a_owner", "OE212 Shop A")
        owner_b, _profile_b = _make_retailer("oe212_b_owner", "OE212 Shop B")
        customer = _make_customer("oe212_shared", phone="9000002107")
        product = _product(profile_a)
        RetailerCustomerMapping.objects.create(retailer=profile_a, customer=customer)
        order = _order(customer, profile_a, product, source="app")

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(reverse(LOOKUP_URL), {"phone": "9000002107"})
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "recent_orders" not in resp.data
        assert Order.objects.filter(id=order.id, retailer=profile_a).exists()

    def test_lookup_query_budget(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("oe212_owner_q", "OE212 Query Shop")
        customer = _make_customer("oe212_q_cust", phone="9000002108")
        product = _product(profile)
        RetailerCustomerMapping.objects.create(retailer=profile, customer=customer)
        _order(customer, profile, product, source="pos")
        _order(customer, profile, product, source="app")

        api_client.force_authenticate(user=owner)
        url = reverse(LOOKUP_URL)
        # Warm org / module-flag rows so the budget is the hot path.
        api_client.get(url, {"phone": "9000002108"})
        with django_assert_num_queries(6):
            resp = api_client.get(url, {"phone": "9000002108"})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["recent_orders"]) == 2
