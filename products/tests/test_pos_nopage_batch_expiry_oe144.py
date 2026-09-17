"""
OE-144 / F-0067 — POS no_page active batch rows include expiry_date.

Thin EXTEND only. Same optional date as ProductBatchSerializer (null OK).
No new expiry policy. Tenancy/auth unchanged.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBatch, ProductCategory
from products.serializers import ProductBatchSerializer
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile


def _today():
    return timezone.localdate()


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


def _make_customer(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
    )


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_batched_product(retailer, category, name):
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal("50.00"),
        has_batches=True,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def _make_batch(product, number, quantity, expiry=None, is_active=True):
    return ProductBatch.objects.create(
        product=product,
        retailer=product.retailer,
        batch_number=number,
        price=product.price,
        quantity=quantity,
        is_active=is_active,
        expiry_date=expiry,
    )


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _expiry_wire(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _pos_batches(api_client, product_id):
    resp = api_client.get(reverse("get_retailer_products"), {"no_page": "true"})
    assert resp.status_code == status.HTTP_200_OK
    return _row_by_id(resp.data, product_id)["batches"]


@pytest.mark.django_db
class TestPosNopageBatchExpiry:
    def test_active_batches_include_dated_and_null_expiry(self, api_client):
        owner, shop = _make_retailer("oe144_pos_own", "OE144 POS Shop")
        category = _make_category(shop, "OE144 POS Cat")
        product = _make_batched_product(shop, category, "OE144 Milk")
        dated = _make_batch(
            product, "DATED", Decimal("4.000"), expiry=_today() + timedelta(days=9)
        )
        undated = _make_batch(product, "NULL", Decimal("2.000"), expiry=None)
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        batches = {row["id"]: row for row in _pos_batches(api_client, product.id)}

        assert dated.id in batches
        assert undated.id in batches
        assert _expiry_wire(batches[dated.id]["expiry_date"]) == (
            ProductBatchSerializer(dated).data["expiry_date"]
        )
        assert _expiry_wire(batches[undated.id]["expiry_date"]) == (
            ProductBatchSerializer(undated).data["expiry_date"]
        )
        assert ProductBatchSerializer(undated).data["expiry_date"] is None

    def test_inactive_batch_is_omitted(self, api_client):
        owner, shop = _make_retailer("oe144_inact_own", "OE144 Inactive Shop")
        category = _make_category(shop, "OE144 Inactive Cat")
        product = _make_batched_product(shop, category, "OE144 Oil")
        active = _make_batch(
            product, "LIVE", Decimal("3.000"), expiry=_today() + timedelta(days=4)
        )
        _make_batch(
            product,
            "DEAD",
            Decimal("7.000"),
            expiry=_today() + timedelta(days=3),
            is_active=False,
        )
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        batches = _pos_batches(api_client, product.id)
        assert [row["id"] for row in batches] == [active.id]
        assert _expiry_wire(batches[0]["expiry_date"]) == (
            ProductBatchSerializer(active).data["expiry_date"]
        )

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe144_auth_own", "OE144 Auth Shop")
        category = _make_category(shop, "OE144 Auth Cat")
        product = _make_batched_product(shop, category, "OE144 Auth Rice")
        _make_batch(product, "LIVE", Decimal("1.000"), expiry=_today())
        customer = _make_customer("oe144_auth_cust")

        anon = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        api_client.force_authenticate(user=owner)
        ok = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert ok.status_code == status.HTTP_200_OK
        assert _row_by_id(ok.data, product.id)["batches"]

    def test_no_cross_tenant_read(self, api_client):
        _owner_a, shop_a = _make_retailer("oe144_ten_a", "OE144 Tenant A")
        owner_b, shop_b = _make_retailer("oe144_ten_b", "OE144 Tenant B")
        category_a = _make_category(shop_a, "OE144 A Cat")
        category_b = _make_category(shop_b, "OE144 B Cat")
        product_a = _make_batched_product(shop_a, category_a, "OE144 A Milk")
        product_b = _make_batched_product(shop_b, category_b, "OE144 B Wheat")
        hidden = _make_batch(
            product_a, "A1", Decimal("10.000"), expiry=_today() + timedelta(days=2)
        )
        visible = _make_batch(
            product_b, "B1", Decimal("5.000"), expiry=_today() + timedelta(days=6)
        )
        product_a.sync_inventory_from_batches()
        product_b.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner_b)
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert pos.status_code == status.HTTP_200_OK
        pos_ids = {row["id"] for row in pos.data}
        assert product_a.id not in pos_ids
        assert product_b.id in pos_ids
        batches = {row["id"]: row for row in _row_by_id(pos.data, product_b.id)["batches"]}
        assert hidden.id not in batches
        assert visible.id in batches
        assert _expiry_wire(batches[visible.id]["expiry_date"]) == (
            ProductBatchSerializer(visible).data["expiry_date"]
        )
