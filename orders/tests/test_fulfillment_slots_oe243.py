"""
OE-243 / F-0115 — Pickup and delivery fulfillment windows (RCP API only).

Vineet lock: 30-minute slots (Asia/Kolkata), hours from RetailerOperatingHours,
retailer-configurable capacity, no hard cutoff, express skipped v1.
"""
from datetime import datetime, time
from decimal import Decimal
from unittest.mock import patch

import pytest
import pytz
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from cart.models import Cart, CartItem
from customers.models import CustomerAddress, CustomerProfile
from orders.models import Order
from products.models import Product, ProductCategory, ProductBrand
from retailers.models import (
    OrgRole,
    OrgStaffMembership,
    RetailerOperatingHours,
    RetailerProfile,
)
from retailers.organization import ensure_organization_for_profile

IST = pytz.timezone('Asia/Kolkata')
FROZEN_NOW = IST.localize(datetime(2026, 9, 7, 10, 0, 0))
FROZEN_NOW_UTC = FROZEN_NOW.astimezone(pytz.UTC)


def _frozen_now():
    return FROZEN_NOW_UTC


def _make_retailer(username, shop_name, *, slot_capacity=5):
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
        accepts_cod=True,
        accepts_upi=True,
        minimum_order_amount=Decimal("0"),
        timezone="Asia/Kolkata",
        fulfillment_slot_capacity=slot_capacity,
    )
    org = ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    for day in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ):
        RetailerOperatingHours.objects.create(
            retailer=profile,
            day_of_week=day,
            is_open=True,
            opening_time=time(9, 0),
            closing_time=time(18, 0),
        )
    return user, profile, org


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
        is_active=True,
        is_available=True,
        track_inventory=False,
        minimum_order_quantity=1,
    )


def _address(customer):
    return CustomerAddress.objects.create(
        customer=customer,
        title="Home",
        address_line1="1 Road",
        city="City",
        state="State",
        pincode="110001",
        is_default=True,
        is_active=True,
    )


def _cart_with_item(customer, retailer, product):
    cart, _ = Cart.objects.get_or_create(customer=customer, retailer=retailer)
    CartItem.objects.create(cart=cart, product=product, quantity=1)
    return cart


def _slot_start_local(hour, minute=0):
    return IST.localize(datetime(2026, 9, 7, hour, minute, 0))


def _slots_url(retailer_id):
    return reverse("list_fulfillment_slots", kwargs={"retailer_id": retailer_id})


def _config_url(org_id):
    return reverse("organization_fulfillment_slot_config", kwargs={"org_id": org_id})


@pytest.mark.django_db
@patch("django.utils.timezone.now", side_effect=_frozen_now)
class TestFulfillmentSlotList:
    def test_lists_thirty_minute_open_slots(self, mock_now, api_client):
        _, profile, _ = _make_retailer("oe243_list", "List Shop")
        resp = api_client.get(
            _slots_url(profile.id),
            {"delivery_mode": "pickup", "days": 1},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["slot_capacity"] == 5
        assert resp.data["timezone"] == "Asia/Kolkata"
        starts_local = [s["slot_start_local"] for s in resp.data["slots"]]
        assert any("T10:00:00" in value for value in starts_local)
        assert any("T10:30:00" in value for value in starts_local)
        assert all(s["is_available"] for s in resp.data["slots"])

    def test_closed_day_yields_no_slots(self, mock_now, api_client):
        _, profile, _ = _make_retailer("oe243_closed", "Closed Shop")
        RetailerOperatingHours.objects.filter(
            retailer=profile, day_of_week="monday"
        ).update(is_open=False)
        resp = api_client.get(_slots_url(profile.id), {"days": 1})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["slots"] == []


@pytest.mark.django_db
@patch("django.utils.timezone.now", side_effect=_frozen_now)
class TestFulfillmentSlotBooking:
    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_books_open_slot(
        self, mock_silent, mock_push, mock_now, api_client
    ):
        _, profile, _ = _make_retailer("oe243_book", "Book Shop")
        customer = _make_customer("oe243_book_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)
        address = _address(customer)
        slot = _slot_start_local(11, 0)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "address_id": address.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "fulfillment_slot_start": slot.isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        order = Order.objects.get(pk=resp.data["id"])
        assert order.fulfillment_slot_start is not None
        assert order.fulfillment_slot_start.astimezone(IST).hour == 11

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_overbook_rejected(self, mock_silent, mock_push, mock_now, api_client):
        _, profile, _ = _make_retailer("oe243_full", "Full Shop", slot_capacity=1)
        customer_a = _make_customer("oe243_full_a")
        customer_b = _make_customer("oe243_full_b")
        product = _product(profile)
        _cart_with_item(customer_a, profile, product)
        _cart_with_item(customer_b, profile, product)
        address_a = _address(customer_a)
        address_b = _address(customer_b)
        slot = _slot_start_local(12, 0)

        api_client.force_authenticate(user=customer_a)
        first = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "address_id": address_a.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "fulfillment_slot_start": slot.isoformat(),
            },
            format="json",
        )
        assert first.status_code == status.HTTP_201_CREATED

        api_client.force_authenticate(user=customer_b)
        second = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "address_id": address_b.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "fulfillment_slot_start": slot.isoformat(),
            },
            format="json",
        )
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert "fulfillment_slot_start" in second.data

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_closed_slot_rejected(self, mock_silent, mock_push, mock_now, api_client):
        _, profile, _ = _make_retailer("oe243_badslot", "Bad Slot Shop")
        customer = _make_customer("oe243_badslot_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)
        address = _address(customer)
        slot = _slot_start_local(20, 0)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "address_id": address.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "fulfillment_slot_start": slot.isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "fulfillment_slot_start" in resp.data


@pytest.mark.django_db
@patch("django.utils.timezone.now", side_effect=_frozen_now)
class TestFulfillmentSlotReschedule:
    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_customer_reschedule_within_open_capacity(
        self, mock_silent, mock_push, mock_now, api_client
    ):
        _, profile, _ = _make_retailer("oe243_resched", "Resched Shop")
        customer = _make_customer("oe243_resched_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)
        address = _address(customer)
        slot = _slot_start_local(13, 0)
        new_slot = _slot_start_local(14, 0)

        api_client.force_authenticate(user=customer)
        placed = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "address_id": address.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "fulfillment_slot_start": slot.isoformat(),
            },
            format="json",
        )
        order_id = placed.data["id"]
        resp = api_client.patch(
            reverse("reschedule_order_fulfillment_slot", args=[order_id]),
            {"fulfillment_slot_start": new_slot.isoformat()},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order = Order.objects.get(pk=order_id)
        assert order.fulfillment_slot_start.astimezone(IST).hour == 14

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_staff_reschedule(self, mock_silent, mock_push, mock_now, api_client):
        owner, profile, org = _make_retailer("oe243_staff", "Staff Shop")
        staff = _make_staff(org, "oe243_staff_member", ["orders.update"])
        customer = _make_customer("oe243_staff_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)
        address = _address(customer)
        slot = _slot_start_local(15, 0)
        new_slot = _slot_start_local(16, 0)

        api_client.force_authenticate(user=customer)
        placed = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "address_id": address.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "fulfillment_slot_start": slot.isoformat(),
            },
            format="json",
        )
        order_id = placed.data["id"]

        api_client.force_authenticate(user=staff)
        resp = api_client.patch(
            reverse("retailer_reschedule_order_fulfillment_slot", args=[order_id]),
            {"fulfillment_slot_start": new_slot.isoformat()},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        order = Order.objects.get(pk=order_id)
        assert order.fulfillment_slot_start.astimezone(IST).hour == 16


@pytest.mark.django_db
@patch("django.utils.timezone.now", side_effect=_frozen_now)
class TestFulfillmentSlotPermissions:
    def test_config_patch_requires_fulfillment_manage(self, mock_now, api_client):
        owner, profile, org = _make_retailer("oe243_perm", "Perm Shop")
        cashier = _make_staff(org, "oe243_cashier", [])
        api_client.force_authenticate(user=cashier)
        resp = api_client.patch(
            _config_url(org.id),
            {
                "location_id": profile.id,
                "fulfillment_slot_capacity": 10,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        profile.refresh_from_db()
        assert profile.fulfillment_slot_capacity == 5

    def test_config_patch_with_permission(self, mock_now, api_client):
        owner, profile, org = _make_retailer("oe243_cfg", "Cfg Shop")
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            _config_url(org.id),
            {
                "location_id": profile.id,
                "fulfillment_slot_capacity": 8,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        profile.refresh_from_db()
        assert profile.fulfillment_slot_capacity == 8

    def test_cross_tenant_config_forbidden(self, mock_now, api_client):
        _, profile_a, org_a = _make_retailer("oe243_tenant_a", "Tenant A")
        owner_b, _, org_b = _make_retailer("oe243_tenant_b", "Tenant B")
        api_client.force_authenticate(user=owner_b)
        resp = api_client.patch(
            _config_url(org_a.id),
            {
                "location_id": profile_a.id,
                "fulfillment_slot_capacity": 99,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        profile_a.refresh_from_db()
        assert profile_a.fulfillment_slot_capacity == 5


@pytest.mark.django_db
@patch("django.utils.timezone.now", side_effect=_frozen_now)
class TestFulfillmentSlotQueryCounts:
    def test_list_slots_query_count(self, mock_now, api_client, django_assert_num_queries):
        _, profile, _ = _make_retailer("oe243_q_list", "Q List Shop")
        with django_assert_num_queries(3):
            resp = api_client.get(
                _slots_url(profile.id),
                {"delivery_mode": "pickup", "days": 2},
            )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["slots"]) > 0

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_with_slot_query_count(
        self, mock_silent, mock_push, mock_now, api_client, django_assert_num_queries
    ):
        _, profile, _ = _make_retailer("oe243_q_place", "Q Place Shop")
        customer = _make_customer("oe243_q_place_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)
        address = _address(customer)
        slot = _slot_start_local(11, 30)

        api_client.force_authenticate(user=customer)
        with django_assert_num_queries(53):
            resp = api_client.post(
                reverse("place_order"),
                {
                    "retailer_id": profile.id,
                    "address_id": address.id,
                    "delivery_mode": "delivery",
                    "payment_mode": "cash",
                    "fulfillment_slot_start": slot.isoformat(),
                },
                format="json",
            )
        assert resp.status_code == status.HTTP_201_CREATED

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_reschedule_query_count(
        self, mock_silent, mock_push, mock_now, api_client, django_assert_num_queries
    ):
        _, profile, _ = _make_retailer("oe243_q_resched", "Q Resched Shop")
        customer = _make_customer("oe243_q_resched_cust")
        product = _product(profile)
        _cart_with_item(customer, profile, product)
        address = _address(customer)
        slot = _slot_start_local(12, 30)
        new_slot = _slot_start_local(13, 0)

        api_client.force_authenticate(user=customer)
        placed = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": profile.id,
                "address_id": address.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "fulfillment_slot_start": slot.isoformat(),
            },
            format="json",
        )
        order_id = placed.data["id"]

        with django_assert_num_queries(34):
            resp = api_client.patch(
                reverse("reschedule_order_fulfillment_slot", args=[order_id]),
                {"fulfillment_slot_start": new_slot.isoformat()},
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
