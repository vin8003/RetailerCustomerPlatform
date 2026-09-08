"""
OE-152 / F-0054 — App order / shop pickup.

Scope lock: F-0113 and F-0029 are NOT on this stack. Reuses existing ATP hooks
(restore_order_inventory) and OE-183 dispatch only. Pickup = delivery_mode +
Order.status on unified Order — no second table, no marketplace.

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
from orders.pickup import expire_uncollected_pickup_orders
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


def _packed_pickup_order(customer, retailer, product, *, pickup_code="123456"):
    order = Order.objects.create(
        customer=customer,
        retailer=retailer,
        delivery_mode="pickup",
        payment_mode="cash_pickup",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
        status="packed",
        source="app",
        pickup_code=pickup_code,
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
        assert len(order.pickup_code) == 6
        assert order.pickup_code.isdigit()

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


@pytest.mark.django_db
class TestPickupCollectionVerification:
    """AC3 — mark_delivered requires pickup_code / customer id verification."""

    def test_mark_delivered_without_code_denied_order_unchanged(self, api_client):
        owner, profile = _make_retailer("oe152_verify_deny", "Verify Deny")
        customer = _make_customer("oe152_verify_deny_cust")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product, pickup_code="654321")

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_delivered"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "pickup_code" in resp.data
        order.refresh_from_db()
        assert order.status == "packed"

    def test_mark_delivered_with_wrong_code_denied(self, api_client):
        owner, profile = _make_retailer("oe152_verify_wrong", "Verify Wrong")
        customer = _make_customer("oe152_verify_wrong_cust")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product, pickup_code="111111")

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_delivered", "pickup_code": "999999"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "packed"

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_mark_delivered_with_valid_code_succeeds(
        self, mock_dispatch, api_client
    ):
        owner, profile = _make_retailer("oe152_verify_ok", "Verify OK")
        customer = _make_customer("oe152_verify_ok_cust")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product, pickup_code="424242")

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {
                "action": "mark_delivered",
                "pickup_code": "424242",
                "customer_id": customer.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "delivered"
        mock_dispatch.assert_called_once()

    def test_mark_delivered_with_mismatched_customer_id_denied(self, api_client):
        owner, profile = _make_retailer("oe152_verify_cust", "Verify Cust")
        customer = _make_customer("oe152_verify_cust_owner")
        other = _make_customer("oe152_verify_cust_other")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product, pickup_code="808080")

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {
                "action": "mark_delivered",
                "pickup_code": "808080",
                "customer_id": other.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "packed"

    def test_direct_status_delivered_requires_pickup_code(self, api_client):
        owner, profile = _make_retailer("oe152_status_verify", "Status Verify")
        customer = _make_customer("oe152_status_cust")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product, pickup_code="303030")

        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "delivered"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "packed"


@pytest.mark.django_db
class TestUncollectedPickupExpiry:
    """AC4 — policy hours expiry releases ATP and cancels uncollected pickup."""

    def test_expire_uncollected_pickup_restores_atp_and_cancels(self):
        from django.utils import timezone

        owner, profile = _make_retailer("oe152_expire_shop", "Expire Shop")
        profile.pickup_uncollected_hours = 24
        profile.save(update_fields=["pickup_uncollected_hours"])
        customer = _make_customer("oe152_expire_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity

        ready_at = timezone.now() - timezone.timedelta(hours=25)
        order = _packed_pickup_order(customer, profile, product)
        order.pickup_ready_at = ready_at
        order.save(update_fields=["pickup_ready_at"])

        expired = expire_uncollected_pickup_orders(now=timezone.now(), actor=owner)
        assert len(expired) == 1
        assert expired[0]["order_id"] == order.id

        order.refresh_from_db()
        assert order.status == "cancelled"
        assert order.cancelled_by == "system"
        assert "Uncollected shop pickup expired" in order.cancellation_reason
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1

    def test_within_policy_window_not_expired(self):
        from django.utils import timezone

        owner, profile = _make_retailer("oe152_no_expire", "No Expire")
        profile.pickup_uncollected_hours = 48
        profile.save(update_fields=["pickup_uncollected_hours"])
        customer = _make_customer("oe152_no_expire_cust")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product)
        order.pickup_ready_at = timezone.now() - timezone.timedelta(hours=12)
        order.save(update_fields=["pickup_ready_at"])

        expired = expire_uncollected_pickup_orders(now=timezone.now(), actor=owner)
        assert expired == []
        order.refresh_from_db()
        assert order.status == "packed"

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_inbox_mark_packed_sets_pickup_ready_at(self, mock_dispatch, api_client):
        owner, profile = _make_retailer("oe152_ready_at", "Ready At Shop")
        customer = _make_customer("oe152_ready_at_cust")
        product = _product(profile)
        order = Order.objects.create(
            customer=customer,
            retailer=profile,
            delivery_mode="pickup",
            payment_mode="cash_pickup",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="processing",
            source="app",
            pickup_code="121212",
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
            {"action": "mark_packed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "packed"
        assert order.pickup_ready_at is not None


@pytest.mark.django_db
class TestPickupQueryCounts:
    """Hot-path query budgets (OE-152 eng-rules)."""

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_pickup_order_query_count(
        self, mock_silent, mock_push, api_client, django_assert_num_queries
    ):
        _owner, profile = _make_retailer("oe152_q_place", "Q Place Shop")
        customer = _make_customer("oe152_q_place_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)

        api_client.force_authenticate(user=customer)
        with django_assert_num_queries(45):
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

    def test_inbox_pickup_filter_query_count(
        self, api_client, django_assert_num_queries
    ):
        owner, profile = _make_retailer("oe152_q_inbox", "Q Inbox Shop")
        customer = _make_customer("oe152_q_inbox_cust")
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
        with django_assert_num_queries(9):
            resp = api_client.get(
                reverse("list_retailer_inbox"),
                {"source": "app", "delivery_mode": "pickup"},
            )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_mark_delivered_pickup_query_count(
        self, mock_dispatch, api_client, django_assert_num_queries
    ):
        owner, profile = _make_retailer("oe152_q_deliver", "Q Deliver Shop")
        customer = _make_customer("oe152_q_deliver_cust")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product, pickup_code="424242")

        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(35):
            resp = api_client.post(
                reverse("retailer_inbox_action", args=[order.id]),
                {
                    "action": "mark_delivered",
                    "pickup_code": "424242",
                    "customer_id": customer.id,
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK

    def test_expire_uncollected_pickup_query_count(self, django_assert_num_queries):
        owner, profile = _make_retailer("oe152_q_expire", "Q Expire Shop")
        profile.pickup_uncollected_hours = 24
        profile.save(update_fields=["pickup_uncollected_hours"])
        customer = _make_customer("oe152_q_expire_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        order = _packed_pickup_order(customer, profile, product)
        from django.utils import timezone

        order.pickup_ready_at = timezone.now() - timezone.timedelta(hours=25)
        order.save(update_fields=["pickup_ready_at"])

        with django_assert_num_queries(14):
            expired = expire_uncollected_pickup_orders(now=timezone.now(), actor=owner)
        assert len(expired) == 1
        assert expired[0]["order_id"] == order.id
