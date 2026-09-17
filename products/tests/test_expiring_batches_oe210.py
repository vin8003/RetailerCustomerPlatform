"""
OE-210 / F-0125 — shop-scoped expiring/expired batch list (thin EXTEND).

Retailer GET of this shop's active on-hand batches with expiry_date <= today+N
(default N=30). Includes expired lots still on the shelf. Tenant-scoped.
No notify / push / MIS invent.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBatch, ProductCategory
from retailers.models import OrgRole, OrgStaffMembership, RetailerProfile
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


def _make_product(shop, name):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=shop)
    return Product.objects.create(
        retailer=shop,
        name=name,
        category=category,
        price=Decimal("20.00"),
        quantity=10,
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


def _url():
    return reverse("erp-expiring-batches")


def _ids(payload):
    return [row["id"] for row in payload]


@pytest.mark.django_db
class TestExpiringBatchesApi:
    def test_default_window_is_today_plus_30(self, api_client):
        owner, shop = _make_retailer("oe210_def_own", "OE210 Default Shop")
        product = _make_product(shop, "OE210 Milk")
        expired = _make_batch(
            product, "EXP", Decimal("4.000"), expiry=_today() - timedelta(days=2)
        )
        soon = _make_batch(
            product, "SOON", Decimal("3.000"), expiry=_today() + timedelta(days=10)
        )
        on_edge = _make_batch(
            product, "EDGE", Decimal("2.000"), expiry=_today() + timedelta(days=30)
        )
        later = _make_batch(
            product, "LATER", Decimal("5.000"), expiry=_today() + timedelta(days=31)
        )
        _make_batch(product, "NULL", Decimal("6.000"), expiry=None)

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _ids(resp.data) == [expired.id, soon.id, on_edge.id]
        assert later.id not in _ids(resp.data)
        by_id = {row["id"]: row for row in resp.data}
        assert by_id[soon.id]["expiry_date"] == (
            _today() + timedelta(days=10)
        ).isoformat()
        assert by_id[soon.id]["product_id"] == product.id
        assert by_id[soon.id]["product_name"] == "OE210 Milk"
        assert by_id[soon.id]["quantity"] == "3.000"

    def test_custom_days_narrows_window(self, api_client):
        owner, shop = _make_retailer("oe210_n_own", "OE210 Custom N Shop")
        product = _make_product(shop, "OE210 Curd")
        inside = _make_batch(
            product, "IN7", Decimal("2.000"), expiry=_today() + timedelta(days=7)
        )
        outside = _make_batch(
            product, "OUT8", Decimal("2.000"), expiry=_today() + timedelta(days=8)
        )

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(), {"days": "7"})
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _ids(resp.data) == [inside.id]
        assert outside.id not in _ids(resp.data)

        wide = api_client.get(_url(), {"days": "8"})
        assert wide.status_code == status.HTTP_200_OK, wide.data
        assert _ids(wide.data) == [inside.id, outside.id]

    def test_zero_qty_and_inactive_are_excluded(self, api_client):
        owner, shop = _make_retailer("oe210_qty_own", "OE210 Qty Shop")
        product = _make_product(shop, "OE210 Paneer")
        on_hand = _make_batch(
            product, "ON", Decimal("1.000"), expiry=_today() + timedelta(days=2)
        )
        _make_batch(
            product, "ZERO", Decimal("0.000"), expiry=_today() + timedelta(days=2)
        )
        _make_batch(
            product,
            "OFF",
            Decimal("4.000"),
            expiry=_today() + timedelta(days=2),
            is_active=False,
        )

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _ids(resp.data) == [on_hand.id]

    def test_expired_on_hand_is_included(self, api_client):
        owner, shop = _make_retailer("oe210_exp_own", "OE210 Expired Shop")
        product = _make_product(shop, "OE210 Bread")
        expired = _make_batch(
            product, "STALE", Decimal("8.000"), expiry=_today() - timedelta(days=5)
        )

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(), {"days": "0"})
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _ids(resp.data) == [expired.id]
        assert resp.data[0]["expiry_date"] == (
            _today() - timedelta(days=5)
        ).isoformat()

    def test_invalid_days_is_400(self, api_client):
        owner, shop = _make_retailer("oe210_bad_own", "OE210 Bad Days Shop")
        api_client.force_authenticate(user=owner)
        for raw in ("-1", "abc", "1.5"):
            resp = api_client.get(_url(), {"days": raw})
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, raw
            assert "days" in resp.data["error"]

    def test_staff_without_extra_perm_can_read(self, api_client):
        owner, shop = _make_retailer("oe210_staff_own", "OE210 Staff Shop")
        product = _make_product(shop, "OE210 Ghee")
        batch = _make_batch(
            product, "S1", Decimal("2.000"), expiry=_today() + timedelta(days=1)
        )
        cashier = _make_staff(shop.organization, "oe210_cashier", [])

        api_client.force_authenticate(user=cashier)
        resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _ids(resp.data) == [batch.id]

    def test_customer_gets_403(self, api_client, customer):
        _make_retailer("oe210_cust_own", "OE210 Cust Shop")
        api_client.force_authenticate(user=customer)
        resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.data

    def test_unauthenticated_gets_401(self, api_client):
        resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_batches_are_not_listed(self, api_client):
        owner_a, shop_a = _make_retailer("oe210_a_own", "OE210 A Shop")
        owner_b, shop_b = _make_retailer("oe210_b_own", "OE210 B Shop")
        product_a = _make_product(shop_a, "OE210 A SKU")
        product_b = _make_product(shop_b, "OE210 B SKU")
        batch_a = _make_batch(
            product_a, "A1", Decimal("3.000"), expiry=_today() + timedelta(days=3)
        )
        batch_b = _make_batch(
            product_b, "B1", Decimal("9.000"), expiry=_today() + timedelta(days=3)
        )

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _ids(resp.data) == [batch_b.id]
        assert batch_a.id not in _ids(resp.data)

        empty_shop_owner, _empty = _make_retailer("oe210_empty", "OE210 Empty Shop")
        api_client.force_authenticate(user=empty_shop_owner)
        empty = api_client.get(_url())
        assert empty.status_code == status.HTTP_200_OK, empty.data
        assert empty.data == []

    def test_same_org_other_shop_is_excluded(self, api_client):
        owner_a, shop_a = _make_retailer("oe210_loc_a", "OE210 Loc A")
        owner_b, shop_b = _make_retailer("oe210_loc_b", "OE210 Loc B")
        shop_b.organization = shop_a.organization
        shop_b.save(update_fields=["organization", "updated_at"])

        product_a = _make_product(shop_a, "OE210 Loc A SKU")
        product_b = _make_product(shop_b, "OE210 Loc B SKU")
        batch_a = _make_batch(
            product_a, "LA", Decimal("2.000"), expiry=_today() + timedelta(days=4)
        )
        batch_b = _make_batch(
            product_b, "LB", Decimal("2.000"), expiry=_today() + timedelta(days=4)
        )

        api_client.force_authenticate(user=owner_a)
        resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert _ids(resp.data) == [batch_a.id]
        assert batch_b.id not in _ids(resp.data)

    def test_list_does_not_query_product_per_row(self, api_client):
        owner, shop = _make_retailer("oe210_n1_own", "OE210 Nplus1 Shop")
        for i in range(3):
            product = _make_product(shop, f"OE210 Yogurt {i}")
            _make_batch(
                product,
                f"Y{i}",
                Decimal("2.000"),
                expiry=_today() + timedelta(days=i + 1),
            )

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as captured:
            resp = api_client.get(_url())
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert len(resp.data) == 3
        standalone_product_reads = [
            q["sql"]
            for q in captured.captured_queries
            if 'FROM "product"' in q["sql"] and 'FROM "product_batch"' not in q["sql"]
        ]
        assert standalone_product_reads == []
