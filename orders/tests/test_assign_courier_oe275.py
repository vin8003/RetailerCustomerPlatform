"""
OE-275 / F-0119 — Embedded shop assign courier (OrderDelivery).

Covers AC: staff dispatch delivery orders with courier name/phone (+ optional ETA),
OrderDelivery create/update, OE-183 notify on transition, delivery_info on order
detail (retailer + customer), 403 without permission, cross-tenant deny.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from customers.models import CustomerAddress, CustomerProfile
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


def _delivery_order(customer, retailer, product, *, order_status="packed"):
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
class TestAssignCourierDispatch:
    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_inbox_dispatch_creates_order_delivery(self, mock_dispatch, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("oe275_dispatch", "OE275 Dispatch Shop")
        org = profile.organization
        customer = _make_customer("oe275_dispatch_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product)

        eta = timezone.now() + timezone.timedelta(hours=1)
        staff = _make_staff(org, "oe275_dispatch_staff", ["orders.read", "orders.update"])
        api_client.force_authenticate(user=staff)
        with django_assert_num_queries(45):
            resp = api_client.post(
                reverse("retailer_inbox_action", args=[order.id]),
                {
                    "action": "dispatch",
                    "delivery_person_name": "Ravi Kumar",
                    "delivery_person_phone": "9876543210",
                    "estimated_delivery_time": eta.isoformat(),
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "out_for_delivery"

        delivery = OrderDelivery.objects.get(order=order)
        assert delivery.delivery_person_name == "Ravi Kumar"
        assert delivery.delivery_person_phone == "9876543210"
        assert delivery.estimated_delivery_time is not None
        assert delivery.delivery_status == "assigned"
        mock_dispatch.assert_called_once()

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_patch_status_dispatch_creates_order_delivery(self, mock_dispatch, api_client):
        owner, profile = _make_retailer("oe275_patch", "OE275 Patch Shop")
        customer = _make_customer("oe275_patch_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {
                "status": "out_for_delivery",
                "delivery_person_name": "Suresh",
                "delivery_person_phone": "9123456789",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "out_for_delivery"
        assert OrderDelivery.objects.filter(order=order).exists()
        mock_dispatch.assert_called_once()

    def test_dispatch_without_courier_fields_returns_400(self, api_client):
        owner, profile = _make_retailer("oe275_no_courier", "OE275 No Courier")
        customer = _make_customer("oe275_no_courier_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {"action": "dispatch"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        order.refresh_from_db()
        assert order.status == "packed"
        assert not OrderDelivery.objects.filter(order=order).exists()

    @patch("common.notification_dispatcher.dispatch_order_status_notification")
    def test_redispatch_updates_existing_order_delivery(self, mock_dispatch, api_client):
        owner, profile = _make_retailer("oe275_update", "OE275 Update Shop")
        customer = _make_customer("oe275_update_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product)
        OrderDelivery.objects.create(
            order=order,
            delivery_person_name="Old Name",
            delivery_person_phone="9000000000",
            delivery_status="pending",
        )
        order.status = "packed"
        order.save(update_fields=["status"])

        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {
                "status": "out_for_delivery",
                "delivery_person_name": "New Rider",
                "delivery_person_phone": "9111111111",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        delivery = OrderDelivery.objects.get(order=order)
        assert delivery.delivery_person_name == "New Rider"
        assert delivery.delivery_person_phone == "9111111111"
        assert delivery.delivery_status == "assigned"
        assert OrderDelivery.objects.filter(order=order).count() == 1


@pytest.mark.django_db
class TestAssignCourierOrderDetail:
    def test_retailer_order_detail_includes_delivery_info(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("oe275_detail_r", "OE275 Detail R")
        customer = _make_customer("oe275_detail_r_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product, order_status="out_for_delivery")
        eta = timezone.now() + timezone.timedelta(minutes=45)
        OrderDelivery.objects.create(
            order=order,
            delivery_person_name="Amit",
            delivery_person_phone="9988776655",
            estimated_delivery_time=eta,
            delivery_status="assigned",
        )

        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(21):
            resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_200_OK
        info = resp.data["delivery_info"]
        assert info is not None
        assert info["delivery_person_name"] == "Amit"
        assert info["delivery_person_phone"] == "9988776655"
        assert info["delivery_status"] == "assigned"

    def test_customer_order_detail_includes_delivery_info(self, api_client):
        _owner, profile = _make_retailer("oe275_detail_c", "OE275 Detail C")
        customer = _make_customer("oe275_detail_c_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product, order_status="out_for_delivery")
        OrderDelivery.objects.create(
            order=order,
            delivery_person_name="Priya",
            delivery_person_phone="9876512340",
            delivery_status="assigned",
        )

        api_client.force_authenticate(user=customer)
        resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["delivery_info"]["delivery_person_name"] == "Priya"

    def test_order_detail_without_delivery_info_returns_null(self, api_client):
        owner, profile = _make_retailer("oe275_no_info", "OE275 No Info")
        customer = _make_customer("oe275_no_info_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product, order_status="packed")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["delivery_info"] is None


@pytest.mark.django_db
class TestAssignCourierPermissions:
    def test_staff_without_orders_update_gets_403(self, api_client):
        owner, profile = _make_retailer("oe275_perm", "OE275 Perm Shop")
        org = profile.organization
        customer = _make_customer("oe275_perm_cust")
        product = _product(profile)
        order = _delivery_order(customer, profile, product)

        staff = _make_staff(org, "oe275_perm_staff", ["orders.read"])
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {
                "action": "dispatch",
                "delivery_person_name": "Ravi",
                "delivery_person_phone": "9876543210",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        order.refresh_from_db()
        assert order.status == "packed"
        assert not OrderDelivery.objects.filter(order=order).exists()


@pytest.mark.django_db
class TestAssignCourierCrossTenant:
    def test_cannot_dispatch_other_tenant_order(self, api_client):
        _owner_a, profile_a = _make_retailer("oe275_tenant_a", "Tenant A Shop")
        owner_b, profile_b = _make_retailer("oe275_tenant_b", "Tenant B Shop")
        customer = _make_customer("oe275_tenant_cust")
        product = _product(profile_a)
        order = _delivery_order(customer, profile_a, product)

        api_client.force_authenticate(user=owner_b)
        resp = api_client.post(
            reverse("retailer_inbox_action", args=[order.id]),
            {
                "action": "dispatch",
                "delivery_person_name": "Ravi",
                "delivery_person_phone": "9876543210",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        order.refresh_from_db()
        assert order.status == "packed"
        assert not OrderDelivery.objects.filter(order=order).exists()
