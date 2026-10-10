"""
OE-149 / F-0034 — batch reads include is_expired.

Thin EXTEND only. Derived from ProductBatch.is_expired() (null → false).
List / detail / search / POS no_page, plus OE-210 expiring-batches.
Auth/tenancy unchanged. No alerts/notify invent.
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


def _batches_by_id(rows):
    return {row["id"]: row for row in rows}


@pytest.mark.django_db
class TestProductBatchSerializerIsExpired:
    def test_dated_expired_future_null_and_today(self, retailer, category):
        product = _make_batched_product(retailer, category, "OE149 Serializer Milk")
        expired = _make_batch(
            product, "EXP", Decimal("2.000"), expiry=_today() - timedelta(days=1)
        )
        future = _make_batch(
            product, "FUT", Decimal("2.000"), expiry=_today() + timedelta(days=5)
        )
        undated = _make_batch(product, "NULL", Decimal("2.000"), expiry=None)
        today = _make_batch(product, "TODAY", Decimal("2.000"), expiry=_today())

        assert ProductBatchSerializer(expired).data["is_expired"] is True
        assert ProductBatchSerializer(future).data["is_expired"] is False
        assert ProductBatchSerializer(undated).data["is_expired"] is False
        assert ProductBatchSerializer(today).data["is_expired"] is False
        assert expired.is_expired() is True
        assert future.is_expired() is False
        assert undated.is_expired() is False
        assert today.is_expired() is False


@pytest.mark.django_db
class TestRetailerBatchIsExpiredReads:
    def _surfaces(self, api_client, product):
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        search = api_client.get(
            reverse("search_products"), {"search": product.name}
        )
        pos = api_client.get(
            reverse("get_retailer_products"), {"no_page": "true"}
        )
        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert search.status_code == status.HTTP_200_OK, search.data
        assert pos.status_code == status.HTTP_200_OK, pos.data
        return {
            "list": _row_by_id(listed.data, product.id)["batches"],
            "detail": detail.data["batches"],
            "search": _row_by_id(search.data, product.id)["batches"],
            "pos": _row_by_id(pos.data, product.id)["batches"],
        }

    def test_dated_expired_future_and_null_on_all_surfaces(self, api_client):
        owner, shop = _make_retailer("oe149_read_own", "OE149 Read Shop")
        category = _make_category(shop, "OE149 Read Cat")
        product = _make_batched_product(shop, category, "OE149 Milk")
        expired = _make_batch(
            product, "EXP", Decimal("4.000"), expiry=_today() - timedelta(days=2)
        )
        future = _make_batch(
            product, "FUT", Decimal("3.000"), expiry=_today() + timedelta(days=9)
        )
        undated = _make_batch(product, "NULL", Decimal("2.000"), expiry=None)
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        for surface, rows in self._surfaces(api_client, product).items():
            by_id = _batches_by_id(rows)
            assert set(by_id) == {expired.id, future.id, undated.id}, surface
            assert by_id[expired.id]["is_expired"] is True, surface
            assert by_id[future.id]["is_expired"] is False, surface
            assert by_id[undated.id]["is_expired"] is False, surface
            assert by_id[expired.id]["is_expired"] == (
                ProductBatchSerializer(expired).data["is_expired"]
            )
            assert by_id[undated.id]["is_expired"] == (
                ProductBatchSerializer(undated).data["is_expired"]
            )

    def test_inactive_batch_is_omitted(self, api_client):
        owner, shop = _make_retailer("oe149_inact_own", "OE149 Inactive Shop")
        category = _make_category(shop, "OE149 Inactive Cat")
        product = _make_batched_product(shop, category, "OE149 Oil")
        active = _make_batch(
            product, "LIVE", Decimal("3.000"), expiry=_today() - timedelta(days=1)
        )
        inactive = _make_batch(
            product,
            "DEAD",
            Decimal("7.000"),
            expiry=_today() - timedelta(days=3),
            is_active=False,
        )
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        surfaces = self._surfaces(api_client, product)
        for surface in ("list", "search", "pos"):
            rows = surfaces[surface]
            assert [row["id"] for row in rows] == [active.id], surface
            assert rows[0]["is_expired"] is True, surface
        # Retailer detail still includes inactive lots (unchanged).
        detail = _batches_by_id(surfaces["detail"])
        assert set(detail) == {active.id, inactive.id}
        assert detail[active.id]["is_expired"] is True
        assert detail[inactive.id]["is_expired"] is True

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe149_auth_own", "OE149 Auth Shop")
        category = _make_category(shop, "OE149 Auth Cat")
        product = _make_batched_product(shop, category, "OE149 Auth Rice")
        _make_batch(product, "LIVE", Decimal("1.000"), expiry=_today())
        customer = _make_customer("oe149_auth_cust")

        list_url = reverse("get_retailer_products")
        detail_url = reverse("get_product_detail", args=[product.id])
        search_url = reverse("search_products")
        pos_qs = {"no_page": "true"}
        search_qs = {"search": "OE149 Auth Rice"}

        assert api_client.get(list_url).status_code == status.HTTP_401_UNAUTHORIZED
        assert api_client.get(detail_url).status_code == status.HTTP_401_UNAUTHORIZED
        assert (
            api_client.get(search_url, search_qs).status_code
            == status.HTTP_401_UNAUTHORIZED
        )
        assert (
            api_client.get(list_url, pos_qs).status_code
            == status.HTTP_401_UNAUTHORIZED
        )

        api_client.force_authenticate(user=customer)
        assert api_client.get(list_url).status_code == status.HTTP_403_FORBIDDEN
        assert api_client.get(detail_url).status_code == status.HTTP_403_FORBIDDEN
        assert (
            api_client.get(search_url, search_qs).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert api_client.get(list_url, pos_qs).status_code == status.HTTP_403_FORBIDDEN

        api_client.force_authenticate(user=owner)
        assert api_client.get(list_url).status_code == status.HTTP_200_OK
        assert api_client.get(detail_url).status_code == status.HTTP_200_OK

    def test_no_cross_tenant_read(self, api_client):
        _owner_a, shop_a = _make_retailer("oe149_ten_a", "OE149 Tenant A")
        owner_b, shop_b = _make_retailer("oe149_ten_b", "OE149 Tenant B")
        category_a = _make_category(shop_a, "OE149 A Cat")
        category_b = _make_category(shop_b, "OE149 B Cat")
        product_a = _make_batched_product(shop_a, category_a, "OE149 A Milk")
        product_b = _make_batched_product(shop_b, category_b, "OE149 B Wheat")
        hidden = _make_batch(
            product_a, "A1", Decimal("10.000"), expiry=_today() - timedelta(days=1)
        )
        visible = _make_batch(
            product_b, "B1", Decimal("5.000"), expiry=_today() + timedelta(days=6)
        )
        product_a.sync_inventory_from_batches()
        product_b.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("get_retailer_products"))
        pos = api_client.get(reverse("get_retailer_products"), {"no_page": "true"})
        search = api_client.get(
            reverse("search_products"), {"search": "OE149"}
        )
        detail_hidden = api_client.get(
            reverse("get_product_detail", args=[product_a.id])
        )
        detail_visible = api_client.get(
            reverse("get_product_detail", args=[product_b.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail_hidden.status_code == status.HTTP_404_NOT_FOUND
        assert detail_visible.status_code == status.HTTP_200_OK

        list_ids = {row["id"] for row in (listed.data.get("results") or listed.data)}
        pos_ids = {row["id"] for row in pos.data}
        search_ids = {row["id"] for row in (search.data.get("results") or search.data)}
        assert product_a.id not in list_ids
        assert product_a.id not in pos_ids
        assert product_a.id not in search_ids
        assert product_b.id in list_ids
        assert product_b.id in pos_ids
        assert product_b.id in search_ids
        assert hidden.id not in _batches_by_id(detail_visible.data["batches"])
        assert visible.id in _batches_by_id(detail_visible.data["batches"])
        assert detail_visible.data["batches"][0]["is_expired"] is False


@pytest.mark.django_db
class TestExpiringBatchesIsExpired:
    def test_expiring_list_reuses_serializer_flag(self, api_client):
        owner, shop = _make_retailer("oe149_erp_own", "OE149 ERP Shop")
        category = _make_category(shop, "OE149 ERP Cat")
        product = _make_batched_product(shop, category, "OE149 Bread")
        expired = _make_batch(
            product, "STALE", Decimal("8.000"), expiry=_today() - timedelta(days=5)
        )
        soon = _make_batch(
            product, "SOON", Decimal("3.000"), expiry=_today() + timedelta(days=4)
        )
        _make_batch(product, "NULL", Decimal("6.000"), expiry=None)

        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse("erp-expiring-batches"))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        by_id = _batches_by_id(resp.data)
        assert set(by_id) == {expired.id, soon.id}
        assert by_id[expired.id]["is_expired"] is True
        assert by_id[soon.id]["is_expired"] is False
        assert by_id[expired.id]["is_expired"] == (
            ProductBatchSerializer(expired).data["is_expired"]
        )
        assert by_id[soon.id]["is_expired"] == (
            ProductBatchSerializer(soon).data["is_expired"]
        )
