"""
OE-361 / F follow-on — optional locality on retailer customer detail.

Echo locality only when the attribute exists. Missing field or null
stays null (no invented locality). List serializer stays untouched
(OE-305 contest / list hot path). Auth/tenancy unchanged. READ only.
Dummy / local only — never *.ordereasy.win.
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from customers.models import CustomerAddress, CustomerProfile
from customers.serializers import (
    RetailerCustomerDetailSerializer,
    RetailerCustomerListSerializer,
    customer_locality,
    model_has_locality,
    resolve_customer_detail_locality,
)
from retailers.models import RetailerCustomerMapping, RetailerProfile
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


def _detail_instance(**overrides):
    row = {
        "customer_id": 1,
        "customer_name": "Pat",
        "phone_number": "9000000000",
        "email": "pat@example.com",
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
        "notes": None,
        "credit_limit": Decimal("0.00"),
        "current_balance": Decimal("0.00"),
        "credit_due_days": None,
        "locality": None,
        "recent_orders": [],
        "reward_history": [],
        "retailer_ratings": [],
    }
    row.update(overrides)
    return row


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
        "locality": "Should not appear on list",
    }
    row.update(overrides)
    return row


def _address_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if "customer_address" in q["sql"].lower()
    ]


@pytest.mark.django_db
class TestCustomerLocalityHelper:
    def test_models_on_this_stack_have_no_locality_field(self):
        assert not model_has_locality(CustomerAddress)
        assert not model_has_locality(CustomerProfile)
        assert not model_has_locality(RetailerCustomerMapping)
        assert not model_has_locality(User)
        assert not hasattr(CustomerAddress, "locality")

    def test_missing_attribute_is_null(self):
        assert customer_locality(SimpleNamespace(name="no-locality")) is None

    def test_none_candidate_is_null(self):
        assert customer_locality(None) is None
        assert customer_locality() is None

    def test_present_value_is_echoed(self):
        assert customer_locality(SimpleNamespace(locality="Andheri East")) == "Andheri East"

    def test_null_and_empty_passthrough(self):
        assert customer_locality(SimpleNamespace(locality=None)) is None
        assert customer_locality(SimpleNamespace(locality="")) == ""

    def test_first_candidate_with_attribute_wins(self):
        assert customer_locality(
            SimpleNamespace(name="skip"),
            SimpleNamespace(locality="Bandra"),
            SimpleNamespace(locality="Later"),
        ) == "Bandra"

    def test_resolve_skips_address_query_when_field_missing(self):
        user = _make_customer("loc_helper_cust")
        CustomerAddress.objects.create(
            customer=user,
            title="Home",
            address_line1="1 Lane",
            city="Mumbai",
            state="MH",
            pincode="400001",
            is_default=True,
        )
        with CaptureQueriesContext(connection) as captured:
            value = resolve_customer_detail_locality(user)
        assert value is None
        assert _address_table_reads(captured) == []

    def test_resolve_uses_loaded_mapping_without_address_query(self):
        user = _make_customer("loc_map_cust")
        CustomerAddress.objects.create(
            customer=user,
            title="Home",
            address_line1="1 Lane",
            city="Mumbai",
            state="MH",
            pincode="400001",
            is_default=True,
        )
        mapping = SimpleNamespace(locality="Juhu")
        with CaptureQueriesContext(connection) as captured:
            value = resolve_customer_detail_locality(user, mapping)
        assert value == "Juhu"
        assert _address_table_reads(captured) == []


@pytest.mark.django_db
class TestRetailerCustomerDetailLocality:
    def test_detail_serializer_echoes_present_locality(self):
        data = RetailerCustomerDetailSerializer(
            _detail_instance(locality="Andheri East")
        ).data
        assert data["locality"] == "Andheri East"

    def test_detail_serializer_null_and_empty_passthrough(self):
        assert RetailerCustomerDetailSerializer(
            _detail_instance(locality=None)
        ).data["locality"] is None
        assert RetailerCustomerDetailSerializer(
            _detail_instance(locality="")
        ).data["locality"] == ""

    def test_list_serializer_drops_undeclared_locality(self):
        data = RetailerCustomerListSerializer(_list_instance()).data
        assert "locality" not in data

    def test_http_detail_locality_null_when_field_missing(self, api_client):
        owner, shop = _make_retailer("loc_miss_own", "Loc Missing Shop")
        customer = _make_customer("loc_miss_cust")
        CustomerAddress.objects.create(
            customer=customer,
            title="Home",
            address_line1="1 Lane",
            city="Mumbai",
            state="MH",
            pincode="400001",
            is_default=True,
        )
        RetailerCustomerMapping.objects.create(retailer=shop, customer=customer)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as captured:
            detail = api_client.get(
                reverse("get_customer_details_for_retailer", args=[customer.id])
            )
        assert detail.status_code == status.HTTP_200_OK
        assert "locality" in detail.data
        assert detail.data["locality"] is None
        assert _address_table_reads(captured) == []

    def test_http_list_omits_locality(self, api_client):
        owner, shop = _make_retailer("loc_list_own", "Loc List Shop")
        customer = _make_customer("loc_list_cust")
        RetailerCustomerMapping.objects.create(retailer=shop, customer=customer)

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_customers"))
        assert listed.status_code == status.HTTP_200_OK
        list_row = _row_by_customer_id(listed.data, customer.id)
        assert "locality" not in list_row

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("loc_auth_own", "Loc Auth Shop")
        customer = _make_customer("loc_auth_cust")
        RetailerCustomerMapping.objects.create(retailer=shop, customer=customer)

        anon = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer.id])
        )
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED
        assert "locality" not in getattr(anon, "data", {})

        api_client.force_authenticate(user=customer)
        denied = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer.id])
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN
        assert "locality" not in denied.data

    def test_detail_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("loc_ten_a", "Loc Tenant A")
        owner_b, shop_b = _make_retailer("loc_ten_b", "Loc Tenant B")
        shared = _make_customer("loc_ten_shared")
        RetailerCustomerMapping.objects.create(
            retailer=shop_a,
            customer=shared,
            notes="Shop A only",
        )
        RetailerCustomerMapping.objects.create(
            retailer=shop_b,
            customer=shared,
            notes="Shop B only",
        )

        api_client.force_authenticate(user=owner_a)
        detail_a = api_client.get(
            reverse("get_customer_details_for_retailer", args=[shared.id])
        )
        assert detail_a.status_code == status.HTTP_200_OK
        assert detail_a.data["notes"] == "Shop A only"
        assert detail_a.data["locality"] is None

        api_client.force_authenticate(user=owner_b)
        detail_b = api_client.get(
            reverse("get_customer_details_for_retailer", args=[shared.id])
        )
        assert detail_b.status_code == status.HTTP_200_OK
        assert detail_b.data["notes"] == "Shop B only"
        assert detail_b.data["locality"] is None
        assert detail_b.data["notes"] != detail_a.data["notes"]
