"""
OE-152 / F-0054 — App order / shop pickup.

Covers AC: customer creates app pickup order on unified Order (OE-131),
pickup appears in retailer inbox (app source, OE-135), customer views status,
staff/customer permission matrix, cross-tenant isolation, cancel/reject restores
ATP and can notify via OE-183.
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


def _make_retailer(username, shop_name, *, offers_pickup=True, offers_delivery=True):
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
        offers_delivery=offers_delivery,
        offers_pickup=offers_pickup,
        accepts_cod=True,
        accepts_upi=True,
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


def _make_customer(username):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
        is_phone_verified=True,
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


def _cart_with_item(customer, retailer, product):
    cart = Cart.objects.create(customer=customer, retailer=retailer)
    CartItem.objects.create(
        cart=cart,
        product=product,
        quantity=1,
        unit_price=product.price,
    )
    return cart


@pytest.mark.django_db
class TestCustomerPickupCreate:
    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_customer_can_place_pickup_order(self, mock_silent, mock_push, api_client):
        _owner, profile = _make_retailer("oe152_pickup_shop", "OE152 Pickup Shop")
        customer = _make_customer("oe152_pickup_customer")
        product = _product(profile)
        _cart_with_item(customer, profile, product)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "delivery_mode": "pickup",
                "payment_mode": "cash_pickup",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        order = Order.objects.get(customer=customer, retailer=profile)
        assert order.delivery_mode == "pickup"
        assert order.source == "app"
        assert order.payment_mode == "cash_pickup"
        assert order.delivery_fee == Decimal("0.00")
        assert order.delivery_address is None
        assert order.status == "pending"

    def test_pickup_rejected_when_retailer_does_not_offer_pickup(self, api_client):
        _owner, profile = _make_retailer(
            "oe152_no_pickup",
            "No Pickup Shop",
            offers_pickup=False,
        )
        customer = _make_customer("oe152_no_pickup_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "delivery_mode": "pickup",
                "payment_mode": "cash_pickup",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert not Order.objects.filter(customer=customer).exists()

    def test_pickup_does_not_require_address(self, api_client):
        _owner, profile = _make_retailer("oe152_no_addr", "No Addr Shop")
        customer = _make_customer("oe152_no_addr_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "delivery_mode": "pickup",
                "payment_mode": "upi",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        order = Order.objects.get(customer=customer)
        assert order.delivery_address is None


@pytest.mark.django_db
class TestCustomerPickupView:
    def test_customer_can_view_own_pickup_order(self, api_client):
        _owner, profile = _make_retailer("oe152_view_shop", "View Shop")
        customer = _make_customer("oe152_view_cust")
        product = _product(profile)
        order = Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="confirmed",
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

        api_client.force_authenticate(user=customer)
        resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["delivery_mode"] == "pickup"
        assert resp.data["source"] == "app"

    def test_customer_cannot_view_other_customers_pickup_order(self, api_client):
        _owner, profile = _make_retailer("oe152_other_cust", "Other Cust Shop")
        owner = _make_customer("oe152_order_owner")
        other = _make_customer("oe152_order_other")
        product = _product(profile)
        order = Order.objects.create(
            customer=owner,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
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

        api_client.force_authenticate(user=other)
        resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestPickupInboxVisibility:
    def test_pickup_order_appears_in_retailer_inbox_as_app_source(self, api_client):
        owner, profile = _make_retailer("oe152_inbox_shop", "Inbox Shop")
        customer = _make_customer("oe152_inbox_cust")
        product = _product(profile)
        order = Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
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

        api_client.force_authenticate(user=owner)
        resp = api_client.get(
            reverse("list_retailer_inbox"),
            {"source": "app", "delivery_mode": "pickup"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["id"] == order.id
        assert resp.data["results"][0]["delivery_mode"] == "pickup"

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_staff_can_accept_pickup_order_via_inbox(self, mock_dispatch, api_client):
        owner, profile = _make_retailer("oe152_accept_shop", "Accept Shop")
        org = profile.organization
        customer = _make_customer("oe152_accept_cust")
        product = _product(profile)
        order = Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
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

        staff = _make_staff(org, "oe152_accept_staff", ["orders.read", "orders.update"])
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept", "preparation_time_minutes": 15},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "confirmed"
        mock_dispatch.assert_called_once()

    def test_dispatch_blocked_for_pickup_order(self, api_client):
        owner, profile = _make_retailer("oe152_dispatch_block", "Dispatch Block")
        customer = _make_customer("oe152_dispatch_cust")
        product = _product(profile)
        order = Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="packed",
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

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "dispatch"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "packed"


@pytest.mark.django_db
class TestPickupPermissions:
    def test_customer_jwt_blocked_from_inbox(self, api_client):
        _owner, profile = _make_retailer("oe152_perm_inbox", "Perm Inbox")
        customer = _make_customer("oe152_perm_cust")
        product = _product(profile)
        Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="pending",
            source="app",
        )

        api_client.force_authenticate(user=customer)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_staff_without_orders_read_gets_403_on_inbox(self, api_client):
        owner, profile = _make_retailer("oe152_perm_deny", "Perm Deny")
        org = profile.organization
        customer = _make_customer("oe152_perm_deny_cust")
        product = _product(profile)
        Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="pending",
            source="app",
        )

        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        staff = _make_staff(org, "oe152_cashier", cashier_role.permissions)
        api_client.force_authenticate(user=staff)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPickupCrossTenant:
    def test_retailer_cannot_see_other_tenant_pickup_in_inbox(self, api_client):
        _owner_a, profile_a = _make_retailer("oe152_tenant_a", "Tenant A")
        owner_b, profile_b = _make_retailer("oe152_tenant_b", "Tenant B")
        customer = _make_customer("oe152_tenant_cust")
        product = _product(profile_a)
        Order.objects.create(
            customer=customer,
            retailer=profile_a,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="pending",
            source="app",
        )

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(
            reverse("list_retailer_inbox"),
            {"delivery_mode": "pickup"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_retailer_cannot_read_other_tenant_pickup_order_detail(self, api_client):
        _owner_a, profile_a = _make_retailer("oe152_read_a", "Read A")
        owner_b, profile_b = _make_retailer("oe152_read_b", "Read B")
        customer = _make_customer("oe152_read_cust")
        product = _product(profile_a)
        order = Order.objects.create(
            customer=customer,
            retailer=profile_a,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
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

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestPickupInventoryAndNotify:
    def test_customer_cancel_pickup_restores_atp(self, api_client):
        _owner, profile = _make_retailer("oe152_cancel_atp", "Cancel ATP")
        customer = _make_customer("oe152_cancel_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity

        order = Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
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

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("cancel_order", args=[order.id]),
            {"reason": "Changed plans"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_inbox_reject_pickup_notifies_and_restores_atp(
        self, mock_dispatch, api_client
    ):
        owner, profile = _make_retailer("oe152_reject", "Reject Shop")
        customer = _make_customer("oe152_reject_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity

        order = Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
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

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "reject", "notes": "Closed early"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1
        mock_dispatch.assert_called_once()


@pytest.mark.django_db
class TestPickupModuleGate:
    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_disabled_orders_blocks_pickup_place(
        self, mock_silent, mock_push, api_client
    ):
        _owner, profile = _make_retailer("oe152_mod_place", "Mod Place")
        org = profile.organization
        OrgModuleFlags.objects.filter(organization=org).update(flags={"orders": False})
        customer = _make_customer("oe152_mod_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "delivery_mode": "pickup",
                "payment_mode": "cash_pickup",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
