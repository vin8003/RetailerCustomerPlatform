"""
OE-305 sibling — optional `notes` on retailer customer list.

This slice would echo mapping `notes` on `RetailerCustomerListSerializer`
when the model has the field and the list serializer does not already
expose it. `customers/serializers.py` is contested by OE-305 PR #141
(email/notes/credit scalars), so this sibling is a no-op: no serializer
or view edit.

Locks the tip contract and the deferral. Dummy / local only. Never
`*.ordereasy.win`.
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

# Open PR that owns customers/serializers.py (list + detail scalars).
OE305_CONTESTING_PR = 141


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


def _make_customer(username, **kwargs):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
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
    }
    row.update(overrides)
    return row


@pytest.mark.django_db
class TestRetailerCustomerListNotesDeferred:
    def test_mapping_model_has_notes(self):
        field = RetailerCustomerMapping._meta.get_field("notes")
        assert field.null is True
        assert field.blank is True

    def test_detail_already_exposes_notes(self):
        assert "notes" in RetailerCustomerDetailSerializer().fields

    def test_list_omits_notes_while_serializers_contested(self):
        """No-op: do not declare notes here — #141 owns the list serializer."""
        assert OE305_CONTESTING_PR == 141
        assert "notes" not in RetailerCustomerListSerializer().fields

    def test_list_serializer_drops_undeclared_notes(self):
        data = RetailerCustomerListSerializer(
            _list_instance(notes="VIP walk-in")
        ).data
        assert "notes" not in data
        assert data["customer_name"] == "Pat"

    def test_list_http_omits_notes_detail_includes_notes(self, api_client):
        owner, shop = _make_retailer("oe305n_own_ok", "OE305N Shop")
        customer = _make_customer("oe305n_cust_ok")
        RetailerCustomerMapping.objects.create(
            retailer=shop,
            customer=customer,
            notes="Prefers morning delivery",
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_customers"))
        detail = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer.id])
        )
        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_customer_id(listed.data, customer.id)
        assert "notes" not in list_row
        assert detail.data["notes"] == "Prefers morning delivery"
        assert "recent_orders" not in list_row
        assert "recent_orders" in detail.data

    def test_detail_null_notes_passthrough(self, api_client):
        owner, shop = _make_retailer("oe305n_own_null", "OE305N Null Shop")
        customer = _make_customer("oe305n_cust_null")
        RetailerCustomerMapping.objects.create(
            retailer=shop,
            customer=customer,
            notes=None,
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_customers"))
        detail = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer.id])
        )
        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        list_row = _row_by_customer_id(listed.data, customer.id)
        assert "notes" not in list_row
        assert detail.data["notes"] is None

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe305n_auth_own", "OE305N Auth Shop")
        customer = _make_customer("oe305n_auth_cust")
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
        owner_a, shop_a = _make_retailer("oe305n_ten_a", "OE305N Tenant A")
        owner_b, shop_b = _make_retailer("oe305n_ten_b", "OE305N Tenant B")
        shared = _make_customer("oe305n_ten_shared")
        other = _make_customer("oe305n_ten_other")
        RetailerCustomerMapping.objects.create(
            retailer=shop_a,
            customer=shared,
            notes="Shop A notes",
        )
        RetailerCustomerMapping.objects.create(
            retailer=shop_b,
            customer=shared,
            notes="Shop B notes",
        )
        RetailerCustomerMapping.objects.create(
            retailer=shop_a,
            customer=other,
            notes="Other shop A only",
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
        assert "notes" not in list_b
        assert detail_b.data["notes"] == "Shop B notes"
