"""
OE-135 / F-0050 — Retailer order inbox.

Covers AC: staff list/filter inbox, inbox actions via state machine,
403 without permission, customer JWT blocked, cross-tenant isolation,
orders module gate, OE-183 notification on status change.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch
from django.urls import reverse
from rest_framework import status

from authentication.models import User
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


def _add_location(org, shop_name, *, pincode="110002"):
    loc_user = User.objects.create_user(
        username=f"loc_{shop_name.replace(' ', '_').lower()}",
        email=f"loc_{shop_name.replace(' ', '_').lower()}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    return RetailerProfile.objects.create(
        user=loc_user,
        organization=org,
        shop_name=shop_name,
        address_line1="2 Main",
        city="City",
        state="State",
        pincode=pincode,
        is_active=True,
        offers_delivery=True,
        offers_pickup=True,
        minimum_order_amount=Decimal("0"),
    )


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


def _order(customer, retailer, product, *, order_status="pending", source="app"):
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
        status=order_status,
        source=source,
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
class TestRetailerInboxList:
    def test_staff_with_orders_read_can_list_inbox(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("oe135_list_owner", "OE135 List Shop")
        org = profile.organization
        customer = _make_customer("oe135_list_cust")
        product = _product(profile)
        order = _order(customer, profile, product)

        staff = _make_staff(org, "oe135_list_staff", ["orders.read"])
        api_client.force_authenticate(user=staff)
        with django_assert_num_queries(22):
            resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["id"] == order.id
        assert resp.data["results"][0]["status"] == "pending"

    def test_staff_without_orders_read_gets_403(self, api_client):
        owner, profile = _make_retailer("oe135_list_deny", "OE135 Deny Shop")
        org = profile.organization
        customer = _make_customer("oe135_list_deny_cust")
        product = _product(profile)
        _order(customer, profile, product)

        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        staff = _make_staff(org, "oe135_cashier", cashier_role.permissions)
        api_client.force_authenticate(user=staff)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_customer_jwt_blocked_from_inbox_list(self, api_client):
        _owner, profile = _make_retailer("oe135_cust_block", "OE135 Cust Block")
        customer = _make_customer("oe135_cust_block_user")
        product = _product(profile)
        _order(customer, profile, product)

        api_client.force_authenticate(user=customer)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_inbox_filters_by_status_and_source(self, api_client):
        owner, profile = _make_retailer("oe135_filter", "OE135 Filter Shop")
        customer = _make_customer("oe135_filter_cust")
        product = _product(profile)
        pending = _order(customer, profile, product, order_status="pending", source="app")
        _order(customer, profile, product, order_status="confirmed", source="pos")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(
            reverse("list_retailer_inbox"),
            {"status": "pending", "source": "app"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["id"] == pending.id

    def test_inbox_needs_action_filter(self, api_client):
        owner, profile = _make_retailer("oe135_needs", "OE135 Needs Shop")
        customer = _make_customer("oe135_needs_cust")
        product = _product(profile)
        pending = _order(customer, profile, product, order_status="pending")
        _order(customer, profile, product, order_status="confirmed")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(
            reverse("list_retailer_inbox"),
            {"needs_action": "true"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["id"] == pending.id

    def test_inbox_excludes_delivered_by_default(self, api_client):
        owner, profile = _make_retailer("oe135_excl", "OE135 Excl Shop")
        customer = _make_customer("oe135_excl_cust")
        product = _product(profile)
        _order(customer, profile, product, order_status="delivered")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_inbox_rejects_unknown_source_filter(self, api_client):
        """F-0117 marketplace sources are out of scope — unknown source returns 400."""
        owner, profile = _make_retailer("oe135_src", "OE135 Source Shop")
        customer = _make_customer("oe135_src_cust")
        product = _product(profile)
        _order(customer, profile, product, source="app")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(
            reverse("list_retailer_inbox"),
            {"source": "marketplace"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "source" in resp.data["error"].lower()


@pytest.mark.django_db
class TestRetailerInboxActions:
    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_staff_can_accept_pending_order(self, mock_dispatch, api_client):
        owner, profile = _make_retailer("oe135_accept", "OE135 Accept Shop")
        org = profile.organization
        customer = _make_customer("oe135_accept_cust")
        product = _product(profile)
        order = _order(customer, profile, product)

        staff = _make_staff(org, "oe135_accept_staff", ["orders.read", "orders.update"])
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept", "preparation_time_minutes": 30},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "confirmed"
        assert order.preparation_time_minutes == 30
        mock_dispatch.assert_called_once()

    def test_staff_without_orders_update_gets_403(self, api_client):
        owner, profile = _make_retailer("oe135_act_deny", "OE135 Act Deny")
        org = profile.organization
        customer = _make_customer("oe135_act_deny_cust")
        product = _product(profile)
        order = _order(customer, profile, product)

        staff = _make_staff(org, "oe135_act_cashier", [])
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        order.refresh_from_db()
        assert order.status == "pending"

    def test_customer_jwt_blocked_from_inbox_action(self, api_client):
        _owner, profile = _make_retailer("oe135_act_cust", "OE135 Act Cust")
        customer = _make_customer("oe135_act_cust_user")
        product = _product(profile)
        order = _order(customer, profile, product)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_action_for_status_returns_400(self, api_client):
        owner, profile = _make_retailer("oe135_bad_act", "OE135 Bad Act")
        customer = _make_customer("oe135_bad_act_cust")
        product = _product(profile)
        order = _order(customer, profile, product, order_status="delivered")

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestRetailerInboxInventoryRestore:
    def test_inbox_cancel_restores_product_quantity(self, api_client):
        owner, profile = _make_retailer("oe135_cancel_atp", "Cancel ATP Shop")
        customer = _make_customer("oe135_cancel_atp_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity
        order = _order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "cancel", "notes": "Out of stock"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        assert order.cancellation_reason == "Out of stock"
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1

    def test_inbox_reject_restores_product_quantity(self, api_client):
        owner, profile = _make_retailer("oe135_reject_atp", "Reject ATP Shop")
        customer = _make_customer("oe135_reject_atp_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity
        order = _order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "reject"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1


@pytest.mark.django_db
class TestRetailerInboxPatchCancelAtp:
    def test_patch_cancel_restores_product_quantity(self, api_client):
        owner, profile = _make_retailer("oe135_patch_atp", "Patch Cancel ATP Shop")
        customer = _make_customer("oe135_patch_atp_cust")
        product = _product(profile)
        product.reduce_quantity(1)
        product.refresh_from_db()
        reserved_qty = product.quantity
        order = _order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "cancelled", "notes": "Cannot fulfil"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"
        product.refresh_from_db()
        assert product.quantity == reserved_qty + 1


@pytest.mark.django_db
class TestRetailerInboxLocationScope:
    def test_staff_cannot_accept_order_at_unserved_location(self, api_client):
        owner, l1 = _make_retailer("oe135_unserved_owner", "L1 Shop")
        org = l1.organization
        l2 = _add_location(org, "L2 Shop")
        customer = _make_customer("oe135_unserved_cust")
        product = _product(l1)
        order = _order(customer, l1, product)

        staff = _make_staff(
            org,
            "oe135_l2_only",
            ["orders.read", "orders.update"],
            served_location_ids=[l2.id],
        )
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        order.refresh_from_db()
        assert order.status == "pending"
        product.refresh_from_db()
        assert product.quantity == Decimal("50")

    def test_inbox_list_excludes_unserved_location_orders(self, api_client):
        owner, l1 = _make_retailer("oe135_list_loc", "List L1 Shop")
        org = l1.organization
        l2 = _add_location(org, "List L2 Shop", pincode="110003")
        customer = _make_customer("oe135_list_loc_cust")
        product = _product(l1)
        _order(customer, l1, product)

        staff = _make_staff(
            org,
            "oe135_list_l2",
            ["orders.read"],
            served_location_ids=[l2.id],
        )
        api_client.force_authenticate(user=staff)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0


@pytest.mark.django_db
class TestRetailerInboxCrossTenant:
    def test_cannot_list_other_tenant_orders_via_inbox(self, api_client):
        _owner_a, profile_a = _make_retailer("oe135_tenant_a", "Tenant A")
        owner_b, profile_b = _make_retailer("oe135_tenant_b", "Tenant B")
        customer = _make_customer("oe135_tenant_cust")
        product = _product(profile_a)
        _order(customer, profile_a, product)

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0

    def test_cannot_act_on_other_tenant_order(self, api_client):
        _owner_a, profile_a = _make_retailer("oe135_mut_a", "Mut A")
        owner_b, profile_b = _make_retailer("oe135_mut_b", "Mut B")
        customer = _make_customer("oe135_mut_cust")
        product = _product(profile_a)
        order = _order(customer, profile_a, product)

        api_client.force_authenticate(user=owner_b)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        order.refresh_from_db()
        assert order.status == "pending"


@pytest.mark.django_db
class TestRetailerInboxModuleGate:
    def test_disabled_orders_blocks_inbox_list(self, api_client):
        owner, profile = _make_retailer("oe135_mod_list", "Mod Inbox Shop")
        org = profile.organization
        OrgModuleFlags.objects.filter(organization=org).update(flags={"orders": False})
        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse("list_retailer_inbox"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
        assert resp.data["module"] == "orders"

    def test_disabled_orders_blocks_inbox_action(self, api_client):
        owner, profile = _make_retailer("oe135_mod_act", "Mod Act Shop")
        org = profile.organization
        customer = _make_customer("oe135_mod_act_cust")
        product = _product(profile)
        order = _order(customer, profile, product)
        OrgModuleFlags.objects.filter(organization=org).update(flags={"orders": False})

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "accept"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED


@pytest.mark.django_db
class TestRetailerInboxV1Alias:
    def test_v1_inbox_routes_available(self, api_client):
        owner, profile = _make_retailer("oe135_v1", "V1 Inbox Shop")
        customer = _make_customer("oe135_v1_cust")
        product = _product(profile)
        order = _order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        list_resp = api_client.get("/api/v1/orders/inbox/")
        assert list_resp.status_code == status.HTTP_200_OK

        act_resp = api_client.post(
            f"/api/v1/orders/inbox/{order.id}/actions/",
            {"action": "confirm"},
            format="json",
        )
        assert act_resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "confirmed"
