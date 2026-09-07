"""
OE-131 / F-0049 — Unified order capability (POS + app).

Covers AC: staff create/update with org scoping, customer place/view,
status transitions + notifications hook, RBAC 403, cross-tenant isolation,
orders module gate, customer JWT blocked from staff endpoints.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from cart.models import Cart, CartItem
from customers.models import CustomerAddress, CustomerProfile
from orders.models import Order, OrderItem
from products.models import Product, ProductCategory, ProductBrand
from retailers.models import OrgModuleFlags, OrgRole, OrgStaffMembership, RetailerProfile
from retailers.module_flags_catalog import ERROR_CODE_MODULE_DISABLED
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import ROLE_SLUG_CASHIER


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
        offers_delivery=True,
        offers_pickup=True,
        minimum_order_amount=Decimal("0"),
    )
    ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_staff(org, username, permissions):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    role = OrgRole.objects.create(
        organization=org,
        slug=f"role_{username}",
        name=f"Role {username}",
        permissions=list(permissions),
        is_system=False,
    )
    OrgStaffMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_active=True,
    )
    return user


def _make_customer(username, *, phone_verified=True):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
        is_phone_verified=phone_verified,
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
        minimum_order_quantity=1,
        unit="piece",
    )


def _pending_order(customer, retailer, product):
    address = CustomerAddress.objects.create(
        customer=customer,
        address_line1="1 Lane",
        city="City",
        state="State",
        pincode="110001",
        is_default=True,
    )
    order = Order.objects.create(
        customer=customer,
        retailer=retailer,
        delivery_address=address,
        delivery_mode="delivery",
        payment_mode="cash",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
        status="pending",
        source="app",
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


@pytest.mark.django_db
class TestStaffOrderPermissions:
    def test_staff_with_orders_update_can_change_status(self, api_client):
        owner, profile = _make_retailer("oe131_owner_ok", "OE131 OK Shop")
        org = profile.organization
        customer = _make_customer("oe131_cust_ok")
        product = _product(profile)
        order = _pending_order(customer, profile, product)

        staff = _make_staff(org, "oe131_staff_ok", ["orders.read", "orders.update"])
        api_client.force_authenticate(user=staff)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "confirmed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "confirmed"

    def test_staff_without_orders_update_gets_403_and_unchanged(self, api_client):
        owner, profile = _make_retailer("oe131_owner_deny", "OE131 Deny Shop")
        org = profile.organization
        customer = _make_customer("oe131_cust_deny")
        product = _product(profile)
        order = _pending_order(customer, profile, product)

        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        staff = _make_staff(org, "oe131_cashier", cashier_role.permissions)
        api_client.force_authenticate(user=staff)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "confirmed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        order.refresh_from_db()
        assert order.status == "pending"

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_status_update_dispatches_oe183_notification(
        self, mock_dispatch, api_client
    ):
        owner, profile = _make_retailer("oe131_owner_notify", "OE131 Notify Shop")
        customer = _make_customer("oe131_cust_notify")
        product = _product(profile)
        order = _pending_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "confirmed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        mock_dispatch.assert_called_once()


@pytest.mark.django_db
class TestStaffPosCreate:
    def test_staff_with_orders_create_can_pos_checkout(self, api_client):
        owner, profile = _make_retailer("oe131_pos_owner", "OE131 POS Shop")
        org = profile.organization
        product = _product(profile)
        staff = _make_staff(
            org, "oe131_pos_staff", ["orders.create", "orders.read"]
        )
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("create_pos_order"),
            {
                "location_id": profile.id,
                "items": [
                    {"product_id": product.id, "quantity": 1, "unit_price": "100.00"}
                ],
                "payment_mode": "cash",
                "subtotal": "100.00",
                "discount_amount": "0",
                "total_amount": "100.00",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert Order.objects.filter(retailer=profile, source="pos").exists()

    def test_staff_without_orders_create_blocked_on_pos(self, api_client):
        owner, profile = _make_retailer("oe131_pos_deny", "OE131 POS Deny")
        org = profile.organization
        product = _product(profile)
        staff = _make_staff(org, "oe131_pos_cashier", [])
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("create_pos_order"),
            {
                "location_id": profile.id,
                "items": [
                    {"product_id": product.id, "quantity": 1, "unit_price": "100.00"}
                ],
                "payment_mode": "cash",
                "subtotal": "100.00",
                "total_amount": "100.00",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert not Order.objects.filter(retailer=profile, source="pos").exists()


@pytest.mark.django_db
class TestCustomerOrderPath:
    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_customer_can_place_order(self, mock_silent, mock_push, api_client):
        _owner, profile = _make_retailer("oe131_app_shop", "OE131 App Shop")
        customer = _make_customer("oe131_app_customer")
        product = _product(profile)
        address = CustomerAddress.objects.create(
            customer=customer,
            address_line1="2 Lane",
            city="City",
            state="State",
            pincode="110001",
            is_default=True,
        )
        cart = Cart.objects.create(customer=customer, retailer=profile)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
            unit_price=product.price,
        )
        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "address_id": address.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert Order.objects.filter(customer=customer, retailer=profile).exists()

    def test_customer_can_view_own_order_detail(self, api_client):
        _owner, profile = _make_retailer("oe131_view_shop", "OE131 View Shop")
        customer = _make_customer("oe131_view_customer")
        product = _product(profile)
        order = _pending_order(customer, profile, product)
        api_client.force_authenticate(user=customer)
        resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_200_OK

    def test_customer_cannot_update_order_status(self, api_client):
        _owner, profile = _make_retailer("oe131_cust_mut", "OE131 Cust Mut")
        customer = _make_customer("oe131_cust_mut_user")
        product = _product(profile)
        order = _pending_order(customer, profile, product)
        api_client.force_authenticate(user=customer)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "confirmed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCrossTenantIsolation:
    def test_retailer_cannot_read_other_tenant_order(self, api_client):
        _owner_a, profile_a = _make_retailer("oe131_tenant_a", "Tenant A Shop")
        _owner_b, profile_b = _make_retailer("oe131_tenant_b", "Tenant B Shop")
        customer = _make_customer("oe131_tenant_cust")
        product = _product(profile_a)
        order = _pending_order(customer, profile_a, product)

        api_client.force_authenticate(user=_owner_b)
        resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_retailer_cannot_mutate_other_tenant_order(self, api_client):
        _owner_a, profile_a = _make_retailer("oe131_mut_a", "Mut A Shop")
        _owner_b, profile_b = _make_retailer("oe131_mut_b", "Mut B Shop")
        customer = _make_customer("oe131_mut_cust")
        product = _product(profile_a)
        order = _pending_order(customer, profile_a, product)

        api_client.force_authenticate(user=_owner_b)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "confirmed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        order.refresh_from_db()
        assert order.status == "pending"


@pytest.mark.django_db
class TestOrdersModuleGate:
    def test_disabled_orders_blocks_retailer_list(self, api_client):
        owner, profile = _make_retailer("oe131_mod_list", "Mod List Shop")
        org = profile.organization
        OrgModuleFlags.objects.filter(organization=org).update(flags={"orders": False})
        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse("get_current_orders"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
        assert resp.data["module"] == "orders"

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_disabled_orders_blocks_customer_place_order(
        self, mock_silent, mock_push, api_client
    ):
        _owner, profile = _make_retailer("oe131_mod_place", "Mod Place Shop")
        org = profile.organization
        OrgModuleFlags.objects.filter(organization=org).update(flags={"orders": False})
        customer = _make_customer("oe131_mod_place_cust")
        product = _product(profile)
        address = CustomerAddress.objects.create(
            customer=customer,
            address_line1="3 Lane",
            city="City",
            state="State",
            pincode="110001",
            is_default=True,
        )
        cart = Cart.objects.create(customer=customer, retailer=profile)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
            unit_price=product.price,
        )
        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "address_id": address.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED


@pytest.mark.django_db
class TestV1OrdersAlias:
    def test_v1_orders_status_route_matches_unversioned(self, api_client):
        owner, profile = _make_retailer("oe131_v1", "V1 Shop")
        customer = _make_customer("oe131_v1_cust")
        product = _product(profile)
        order = _pending_order(customer, profile, product)
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            "/api/v1/orders/{0}/status/".format(order.id),
            {"status": "confirmed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
