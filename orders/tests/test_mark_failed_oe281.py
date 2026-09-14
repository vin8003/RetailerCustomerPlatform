"""
OE-281 / D3 — Shop close-out: OFD mark_failed.

Failed write path only. OFD→delivered (status=delivered / mark_delivered)
stays unchanged. Order status stays cancelled (no new failed status).
"""
import pytest
from decimal import Decimal
from unittest.mock import patch
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from customers.models import CustomerAddress, CustomerProfile
from orders.inbox import (
    allowed_inbox_actions_for_status,
    validate_inbox_action,
)
from orders.models import Order, OrderDelivery, OrderItem
from products.models import Product, ProductCategory, ProductBrand
from retailers.models import OrgRole, OrgStaffMembership, RetailerProfile
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
        offers_delivery=True,
        offers_pickup=True,
        minimum_order_amount=Decimal("0"),
    )
    ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_staff(org, username, permissions, *, served_location_ids=None):
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
        served_location_ids=list(served_location_ids or []),
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


def _delivery_ofd_order(customer, retailer, product, *, with_delivery_row=True):
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
        status="out_for_delivery",
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
    if with_delivery_row:
        OrderDelivery.objects.create(
            order=order,
            delivery_person_name="Ravi",
            delivery_person_phone="9876543210",
            delivery_status="assigned",
        )
    return order


def _packed_pickup_order(customer, retailer, product, *, pickup_code="424242"):
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
class TestMarkFailedInboxPolicy:
    def test_mark_failed_maps_ofd_to_cancelled(self):
        assert validate_inbox_action(
            "out_for_delivery",
            "mark_failed",
            delivery_mode="delivery",
        ) == "cancelled"

    def test_mark_failed_rejected_from_pending(self):
        with pytest.raises(ValueError, match="out_for_delivery"):
            validate_inbox_action("pending", "mark_failed", delivery_mode="delivery")

    def test_mark_failed_rejected_for_pickup(self):
        with pytest.raises(ValueError, match="pickup"):
            validate_inbox_action(
                "out_for_delivery",
                "mark_failed",
                delivery_mode="pickup",
            )

    def test_allowed_actions_include_mark_failed_only_on_ofd_delivery(self):
        ofd_actions = allowed_inbox_actions_for_status(
            "out_for_delivery",
            delivery_mode="delivery",
        )
        assert "mark_failed" in ofd_actions
        assert "mark_delivered" in ofd_actions

        pending_actions = allowed_inbox_actions_for_status(
            "pending",
            delivery_mode="delivery",
        )
        assert "mark_failed" not in pending_actions
        assert "cancel" in pending_actions

        pickup_ofd = allowed_inbox_actions_for_status(
            "out_for_delivery",
            delivery_mode="pickup",
        )
        assert "mark_failed" not in pickup_ofd


@pytest.mark.django_db
class TestMarkFailedInboxAction:
    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_ofd_delivery_mark_failed_success(
        self, mock_dispatch, api_client, django_assert_num_queries
    ):
        owner, profile = _make_retailer("oe281_ok", "OE281 OK Shop")
        customer = _make_customer("oe281_ok_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity
        order = _delivery_ofd_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(41):
            resp = api_client.post(
                reverse("retailer_inbox_action", args=[order.id]),
                {
                    "action": "mark_failed",
                    "reason": "Customer not available",
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        assert order.cancellation_reason == "Customer not available"
        assert order.cancelled_by == "retailer"
        delivery = OrderDelivery.objects.get(order=order)
        assert delivery.delivery_status == "failed"
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1
        mock_dispatch.assert_called_once()
        assert mock_dispatch.call_args.kwargs["new_status"] == "cancelled"

    def test_mark_failed_missing_reason_returns_400(self, api_client):
        owner, profile = _make_retailer("oe281_noreason", "OE281 No Reason")
        customer = _make_customer("oe281_noreason_cust")
        product = _product(profile)
        order = _delivery_ofd_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_failed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "reason" in resp.data
        order.refresh_from_db()
        assert order.status == "out_for_delivery"
        assert order.cancellation_reason == ""
        assert OrderDelivery.objects.get(order=order).delivery_status == "assigned"

    def test_mark_failed_blank_reason_returns_400(self, api_client):
        owner, profile = _make_retailer("oe281_blank", "OE281 Blank Reason")
        customer = _make_customer("oe281_blank_cust")
        product = _product(profile)
        order = _delivery_ofd_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_failed", "reason": "   "},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "out_for_delivery"

    def test_staff_without_orders_update_gets_403(self, api_client):
        owner, profile = _make_retailer("oe281_perm", "OE281 Perm Shop")
        org = profile.organization
        customer = _make_customer("oe281_perm_cust")
        product = _product(profile)
        order = _delivery_ofd_order(customer, profile, product)

        staff = _make_staff(org, "oe281_perm_staff", ["orders.read"])
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_failed", "reason": "No answer"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        order.refresh_from_db()
        assert order.status == "out_for_delivery"
        assert order.cancellation_reason == ""

    def test_cross_tenant_mark_failed_returns_404(self, api_client):
        _owner_a, profile_a = _make_retailer("oe281_tenant_a", "Tenant A Shop")
        owner_b, _profile_b = _make_retailer("oe281_tenant_b", "Tenant B Shop")
        customer = _make_customer("oe281_tenant_cust")
        product = _product(profile_a)
        order = _delivery_ofd_order(customer, profile_a, product)

        api_client.force_authenticate(user=owner_b)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_failed", "reason": "Wrong shop"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        order.refresh_from_db()
        assert order.status == "out_for_delivery"
        assert order.cancellation_reason == ""

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_mark_failed_without_delivery_row_still_cancels(
        self, mock_dispatch, api_client
    ):
        owner, profile = _make_retailer("oe281_nodel", "OE281 No Delivery")
        customer = _make_customer("oe281_nodel_cust")
        product = _product(profile)
        order = _delivery_ofd_order(customer, profile, product, with_delivery_row=False)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_failed", "reason": "Address not found"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        assert order.cancellation_reason == "Address not found"
        assert not OrderDelivery.objects.filter(order=order).exists()
        mock_dispatch.assert_called_once()

    def test_second_mark_failed_rejected_order_unchanged(self, api_client):
        owner, profile = _make_retailer("oe281_twice", "OE281 Twice")
        customer = _make_customer("oe281_twice_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        after_first_qty = None
        order = _delivery_ofd_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        first = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_failed", "reason": "Refused"},
            format="json",
        )
        assert first.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        after_first_qty = product.quantity

        second = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_failed", "reason": "Refused again"},
            format="json",
        )
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "cancelled"
        assert order.cancellation_reason == "Refused"
        product.refresh_from_db()
        assert product.quantity == after_first_qty


@pytest.mark.django_db
class TestMarkFailedStatusPath:
    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_ofd_patch_cancelled_requires_reason_and_marks_delivery_failed(
        self, mock_dispatch, api_client
    ):
        owner, profile = _make_retailer("oe281_patch", "OE281 Patch Shop")
        customer = _make_customer("oe281_patch_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity
        order = _delivery_ofd_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        missing = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "cancelled"},
            format="json",
        )
        assert missing.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "out_for_delivery"

        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "cancelled", "reason": "Could not locate customer"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        assert order.cancellation_reason == "Could not locate customer"
        assert order.cancelled_by == "retailer"
        assert OrderDelivery.objects.get(order=order).delivery_status == "failed"
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1
        mock_dispatch.assert_called_once()
        assert mock_dispatch.call_args.kwargs["new_status"] == "cancelled"


@pytest.mark.django_db
class TestDeliveredPathUnchanged:
    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_ofd_delivery_mark_delivered_still_succeeds(self, mock_dispatch, api_client):
        owner, profile = _make_retailer("oe281_delivered", "OE281 Delivered")
        customer = _make_customer("oe281_delivered_cust")
        product = _product(profile)
        order = _delivery_ofd_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_delivered"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "delivered"
        assert order.cancellation_reason == ""
        assert OrderDelivery.objects.get(order=order).delivery_status == "assigned"
        mock_dispatch.assert_called_once()
        assert mock_dispatch.call_args.kwargs["new_status"] == "delivered"

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_ofd_patch_delivered_still_succeeds(self, mock_dispatch, api_client):
        owner, profile = _make_retailer("oe281_patch_del", "OE281 Patch Del")
        customer = _make_customer("oe281_patch_del_cust")
        product = _product(profile)
        order = _delivery_ofd_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "delivered"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "delivered"
        mock_dispatch.assert_called_once()

    def test_pickup_mark_delivered_still_requires_pickup_code(self, api_client):
        owner, profile = _make_retailer("oe281_pickup", "OE281 Pickup")
        customer = _make_customer("oe281_pickup_cust")
        product = _product(profile)
        order = _packed_pickup_order(customer, profile, product, pickup_code="654321")

        api_client.force_authenticate(user=owner)
        denied = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_delivered"},
            format="json",
        )
        assert denied.status_code == status.HTTP_400_BAD_REQUEST
        assert "pickup_code" in denied.data
        order.refresh_from_db()
        assert order.status == "packed"

        ok = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "mark_delivered", "pickup_code": "654321"},
            format="json",
        )
        assert ok.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "delivered"
