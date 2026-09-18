"""
OE-305 / F follow-on — email/notes/credit scalars on retailer customer list.

Same four scalars as customer detail. Null stays null. Do not add
detail-only blobs. Auth/tenancy unchanged. READ only.
Sibling HOT files stay untouched: ProductSearchSerializer Meta (OE-303),
orders/serializers.py (OE-301), products/views.py POS no_page (OE-302).
"""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from customers.models import CustomerProfile
from customers.serializers import (
    RetailerCustomerDetailSerializer,
    RetailerCustomerListSerializer,
)
from products.serializers import ProductSearchSerializer
from retailers.models import RetailerCustomerMapping, RetailerProfile
from retailers.organization import ensure_organization_for_profile

LIST_SCALARS = ("email", "notes", "credit_limit", "credit_due_days")
DETAIL_ONLY_BLOBS = ("recent_orders", "reward_history", "retailer_ratings")

# PR #130 tip (d022f37) — this slice must not edit these sibling files.
PRODUCT_SEARCH_SERIALIZER_SHA256 = (
    "d8fac35801212b933dd7b568ba08b2ee99a57d1aaae6670f8ea3e4d395730f72"
)
ORDERS_SERIALIZERS_SHA256 = (
    "e4abe66276febe3c723d09de59fdd384191e6f7854465a6d3819e65ba213d8a2"
)
PRODUCTS_VIEWS_SHA256 = (
    "6b76e0d7299dc6be89550205b326628ab69f8edac0a1509352f0573d6e05d6c2"
)
SEARCH_META_FIELDS = [
    "id",
    "name",
    "price",
    "app_price",
    "discounted_price",
    "original_price",
    "unit",
    "image",
    "category_name",
    "brand_name",
    "barcode",
    "is_featured",
    "is_active",
    "is_seasonal",
    "product_group",
    "track_inventory",
    "quantity",
    "saleable_quantity",
    "margin_percent",
    "has_batches",
    "batches",
    "is_parent_bulk",
    "parent_bulk_product",
    "conversion_factor",
    "fractional_children",
    "group_variants",
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _file_sha256(relpath):
    return sha256((REPO_ROOT / relpath).read_bytes()).hexdigest()


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

    def test_list_matches_detail_when_scalars_are_null(self, api_client):
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
        customer_a = _make_customer("oe305_ten_cust_a", email="a305@example.com")
        customer_b = _make_customer("oe305_ten_cust_b", email="b305@example.com")
        RetailerCustomerMapping.objects.create(
            retailer=shop_a,
            customer=customer_a,
            notes="Shop A notes",
            credit_limit=Decimal("80.00"),
            credit_due_days=3,
        )
        RetailerCustomerMapping.objects.create(
            retailer=shop_b,
            customer=customer_b,
            notes="Shop B notes",
            credit_limit=Decimal("90.00"),
            credit_due_days=5,
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("get_retailer_customers"))
        detail_b = api_client.get(
            reverse("get_customer_details_for_retailer", args=[customer_b.id])
        )
        assert listed.status_code == status.HTTP_200_OK
        assert detail_b.status_code == status.HTTP_200_OK

        ids = {row["customer_id"] for row in _rows(listed.data)}
        assert customer_a.id not in ids
        assert customer_b.id in ids
        list_b = _row_by_customer_id(listed.data, customer_b.id)
        _assert_scalars_equal(list_b, detail_b.data)
        assert list_b["notes"] == "Shop B notes"

    def test_sibling_hot_files_untouched(self):
        assert _file_sha256("products/serializers.py") == PRODUCT_SEARCH_SERIALIZER_SHA256
        assert _file_sha256("orders/serializers.py") == ORDERS_SERIALIZERS_SHA256
        assert _file_sha256("products/views.py") == PRODUCTS_VIEWS_SHA256
        assert list(ProductSearchSerializer.Meta.fields) == SEARCH_META_FIELDS
        assert "no_page" in (REPO_ROOT / "products" / "views.py").read_text()
        assert RetailerCustomerDetailSerializer().fields.keys() >= set(LIST_SCALARS)
        for blob in DETAIL_ONLY_BLOBS:
            assert blob in RetailerCustomerDetailSerializer().fields
            assert blob not in RetailerCustomerListSerializer().fields
