"""
OE-305 / F follow-on — email/notes/credit scalars on retailer customer list.

Same four scalars as customer detail. Null stays null. Do not add
detail-only blobs. Auth/tenancy unchanged. READ only.
This slice does not edit ProductSearchSerializer Meta (OE-303),
orders/serializers.py (OE-301), or products/views.py POS no_page (OE-302).
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from customers.models import CustomerProfile
from customers.serializers import (
    RetailerCustomerDetailSerializer,
    RetailerCustomerListSerializer,
)
from retailers.models import RetailerCustomerMapping, RetailerProfile
from retailers.organization import ensure_organization_for_profile

LIST_SCALARS = ("email", "notes", "credit_limit", "credit_due_days")
DETAIL_ONLY_BLOBS = ("recent_orders", "reward_history", "retailer_ratings")


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


def _make_customer(username, email=None, **kwargs):
    if email is None:
        email = f"{username}@test.com"
    user = User.objects.create_user(
        username=username,
        email=email,
        password="TestPass123!",
        user_type="customer",
        is_active=True,
        **kwargs,
    )
    CustomerProfile.objects.create(user=user)
    return user


def _rows(payload):
    return payload if isinstance(payload, list) else payload.get("results") or []


def _row_by_customer_id(payload, customer_id):
    for row in _rows(payload):
        if row["customer_id"] == customer_id:
            return row
    raise AssertionError(f"customer {customer_id} missing from payload")


def _list_instance(**overrides):
    row = {
        "customer_id": 1,
        "customer_name": "Pat",
        "phone_number": "9000000000",
        "profile_image": None,
        "points": Decimal("0.00"),
        "average_rating": Decimal("0.00"),
        "total_orders": 0,
        "total_spent": Decimal("0.00"),
        "is_blacklisted": False,
        "last_order_date": None,
        "joined_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "registration_status": "registered",
        "is_phone_verified": True,
        "nickname": None,
        "current_balance": Decimal("0.00"),
        "email": "pat@example.com",
        "notes": "VIP walk-in",
        "credit_limit": Decimal("500.00"),
        "credit_due_days": 14,
    }
    row.update(overrides)
    return row


def _assert_scalars_equal(left, right):
    for key in LIST_SCALARS:
        assert key in left
        assert key in right
        assert left[key] == right[key]


@pytest.mark.django_db
class TestRetailerCustomerListScalars:
    def test_list_serializer_echoes_present_scalars(self):
        data = RetailerCustomerListSerializer(_list_instance()).data
        assert data["email"] == "pat@example.com"
        assert data["notes"] == "VIP walk-in"
        assert Decimal(str(data["credit_limit"])) == Decimal("500.00")
        assert data["credit_due_days"] == 14
        for blob in DETAIL_ONLY_BLOBS:
            assert blob not in data

    def test_list_serializer_null_scalars_stay_null(self):
        data = RetailerCustomerListSerializer(
            _list_instance(
                email=None,
                notes=None,
                credit_limit=None,
                credit_due_days=None,
            )
        ).data
        assert data["email"] is None
        assert data["notes"] is None
        assert data["credit_limit"] is None
        assert data["credit_due_days"] is None

    def test_list_matches_detail_for_present_scalars(self, api_client):
        owner, shop = _make_retailer("oe305_own_ok", "OE305 Shop")
        customer = _make_customer("oe305_cust_ok", email="ok305@example.com")
        RetailerCustomerMapping.objects.create(
            retailer=shop,
            customer=customer,
            notes="Prefers morning delivery",
            credit_limit=Decimal("250.00"),
            credit_due_days=7,
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_customers"))
        detail = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer.id])
        )
        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_customer_id(listed.data, customer.id)
        _assert_scalars_equal(list_row, detail.data)
        assert list_row["email"] == "ok305@example.com"
        assert list_row["notes"] == "Prefers morning delivery"
        assert Decimal(str(list_row["credit_limit"])) == Decimal("250.00")
        assert list_row["credit_due_days"] == 7
        for blob in DETAIL_ONLY_BLOBS:
            assert blob not in list_row
            assert blob in detail.data

    def test_list_matches_detail_when_optional_scalars_unset(self, api_client):
        owner, shop = _make_retailer("oe305_own_null", "OE305 Null Shop")
        customer = _make_customer("oe305_cust_null", email="")
        RetailerCustomerMapping.objects.create(
            retailer=shop,
            customer=customer,
            notes=None,
            credit_limit=Decimal("0.00"),
            credit_due_days=None,
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_customers"))
        detail = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer.id])
        )
        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_customer_id(listed.data, customer.id)
        _assert_scalars_equal(list_row, detail.data)
        assert list_row["email"] in ("", None)
        assert list_row["notes"] is None
        assert list_row["credit_due_days"] is None
        assert Decimal(str(list_row["credit_limit"])) == Decimal("0.00")
        for blob in DETAIL_ONLY_BLOBS:
            assert blob not in list_row

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe305_auth_own", "OE305 Auth Shop")
        customer = _make_customer("oe305_auth_cust")
        RetailerCustomerMapping.objects.create(retailer=shop, customer=customer)

        anon = api_client.get(reverse("get_retailer_customers"))
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(reverse("get_retailer_customers"))
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        api_client.force_authenticate(user=customer)
        detail = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer.id])
        )
        assert detail.status_code == status.HTTP_403_FORBIDDEN

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("oe305_ten_a", "OE305 Tenant A")
        owner_b, shop_b = _make_retailer("oe305_ten_b", "OE305 Tenant B")
        shared = _make_customer("oe305_ten_shared", email="shared305@example.com")
        other = _make_customer("oe305_ten_other", email="other305@example.com")
        RetailerCustomerMapping.objects.create(
            retailer=shop_a,
            customer=shared,
            notes="Shop A notes",
            credit_limit=Decimal("80.00"),
            credit_due_days=3,
        )
        RetailerCustomerMapping.objects.create(
            retailer=shop_b,
            customer=shared,
            notes="Shop B notes",
            credit_limit=Decimal("90.00"),
            credit_due_days=5,
        )
        RetailerCustomerMapping.objects.create(
            retailer=shop_a,
            customer=other,
            notes="Other shop A only",
            credit_limit=Decimal("10.00"),
            credit_due_days=1,
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("get_retailer_customers"))
        detail_b = api_client.get(
            reverse("get_customer_details_for_retailer", args=[shared.id])
        )
        assert listed.status_code == status.HTTP_200_OK
        assert detail_b.status_code == status.HTTP_200_OK

        ids = {row["customer_id"] for row in _rows(listed.data)}
        assert other.id not in ids
        assert shared.id in ids
        list_b = _row_by_customer_id(listed.data, shared.id)
        _assert_scalars_equal(list_b, detail_b.data)
        assert list_b["notes"] == "Shop B notes"
        assert Decimal(str(list_b["credit_limit"])) == Decimal("90.00")
        assert list_b["credit_due_days"] == 5

    def test_list_omits_detail_blobs(self):
        list_fields = set(RetailerCustomerListSerializer().fields)
        detail_fields = set(RetailerCustomerDetailSerializer().fields)
        assert set(LIST_SCALARS) <= list_fields
        assert set(LIST_SCALARS) <= detail_fields
        for blob in DETAIL_ONLY_BLOBS:
            assert blob in detail_fields
            assert blob not in list_fields
