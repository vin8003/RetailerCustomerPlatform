"""
OE-136 / F-0030 — ProductBatch expiry (thin EXTEND).

Stores optional expiry_date, FIFO-picks earliest dated eligible batch,
blocks expired sales (default policy), keeps null-expiry sellable,
gates expiry mutations with inventory.adjust, and denies cross-tenant.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from cart.models import Cart, CartItem
from orders.models import Order
from products.inventory_adjust import (
    PERM_INVENTORY_ADJUST,
    payload_sets_batch_expiry,
    submitted_batch_expiry_differs,
)
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
        offers_delivery=True,
        offers_pickup=True,
        minimum_order_amount=Decimal("0.00"),
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


def _make_location_profile(user, org, shop_name):
    return RetailerProfile.objects.create(
        user=user,
        organization=org,
        shop_name=shop_name,
        address_line1="2 Side",
        city="City",
        state="State",
        pincode="110002",
        is_active=True,
        offers_delivery=True,
        offers_pickup=True,
    )


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_batched_product(retailer, category, name="Expiry Milk"):
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


def _make_batch(product, number, quantity, expiry=None, created_at=None):
    batch = ProductBatch.objects.create(
        product=product,
        retailer=product.retailer,
        batch_number=number,
        price=product.price,
        quantity=quantity,
        is_active=True,
        expiry_date=expiry,
    )
    if created_at is not None:
        ProductBatch.objects.filter(pk=batch.pk).update(created_at=created_at)
        batch.refresh_from_db()
    return batch


def _pos_payload(product, quantity, batch=None, unit_price=None):
    qty = Decimal(str(quantity))
    unit = Decimal(str(unit_price if unit_price is not None else (
        batch.price if batch is not None else product.price
    )))
    line_total = unit * qty
    item = {
        "product_id": product.id,
        "quantity": float(qty),
        "unit_price": float(unit),
    }
    if batch is not None:
        item["batch_id"] = batch.id
    return {
        "payment_mode": "cash",
        "subtotal": float(line_total),
        "total_amount": float(line_total),
        "items": [item],
    }


class TestExpiryPayloadHelpers:
    def test_payload_detects_expiry_key(self):
        assert payload_sets_batch_expiry(
            {"batches": [{"id": 1, "expiry_date": "2026-12-01"}]}
        ) is True
        assert payload_sets_batch_expiry(
            {"batches": [{"id": 1, "price": "9.00"}]}
        ) is False
        assert payload_sets_batch_expiry({"price": "9.00"}) is False

    def test_echoed_expiry_is_not_a_change(self):
        stored = date(2026, 12, 1)
        product = type("P", (), {})()
        product.batches = type("B", (), {
            "filter": lambda *a, **k: [
                type("Row", (), {"id": 7, "expiry_date": stored})()
            ]
        })()
        # Real helper hits product.batches.filter; use a tiny stub below.
        class _QS:
            def __init__(self, rows):
                self._rows = rows

            def only(self, *fields):
                return self._rows

        class _Mgr:
            def filter(self, **kwargs):
                return _QS([type("Row", (), {"id": 7, "expiry_date": stored})()])

        product.batches = _Mgr()
        assert submitted_batch_expiry_differs(
            product, {"batches": [{"id": 7, "expiry_date": "2026-12-01"}]}
        ) is False
        assert submitted_batch_expiry_differs(
            product, {"batches": [{"id": 7, "expiry_date": "2026-12-02"}]}
        ) is True
        assert submitted_batch_expiry_differs(
            product, {"batches": [{"id": 7, "expiry_date": None}]}
        ) is True

    def test_new_batch_with_date_is_a_change_null_is_not(self):
        product = type("P", (), {})()

        class _Mgr:
            def filter(self, **kwargs):
                class _QS:
                    def only(self, *fields):
                        return []
                return _QS()

        product.batches = _Mgr()
        assert submitted_batch_expiry_differs(
            product, {"batches": [{"expiry_date": "2026-12-01", "quantity": 1}]}
        ) is True
        assert submitted_batch_expiry_differs(
            product, {"batches": [{"expiry_date": None, "quantity": 1}]}
        ) is False


@pytest.mark.django_db
class TestExpiryStoredAndFifo:
    def test_expiry_date_is_optional_and_stored(self, retailer, category):
        product = _make_batched_product(retailer, category, name="Store Milk")
        dated = _make_batch(product, "D1", 5, expiry=_today() + timedelta(days=10))
        undated = _make_batch(product, "N1", 5, expiry=None)
        dated.refresh_from_db()
        undated.refresh_from_db()
        assert dated.expiry_date == _today() + timedelta(days=10)
        assert undated.expiry_date is None
        assert dated.is_expired() is False
        assert undated.is_expired() is False

    def test_fifo_picks_earliest_expiry_before_later_and_null(
        self, retailer, category
    ):
        product = _make_batched_product(retailer, category, name="FIFO Milk")
        later = _make_batch(product, "LATER", 10, expiry=_today() + timedelta(days=30))
        sooner = _make_batch(product, "SOON", 10, expiry=_today() + timedelta(days=5))
        undated = _make_batch(product, "NULL", 10, expiry=None)
        product.sync_inventory_from_batches()

        success = product.reduce_quantity(Decimal("12"))
        assert success is True
        later.refresh_from_db()
        sooner.refresh_from_db()
        undated.refresh_from_db()
        assert sooner.quantity == Decimal("0.000")
        assert later.quantity == Decimal("8.000")
        assert undated.quantity == Decimal("10.000")

    def test_null_expiry_batch_still_sells_when_only_stock(
        self, retailer, category
    ):
        product = _make_batched_product(retailer, category, name="Null Milk")
        undated = _make_batch(product, "NULL", 8, expiry=None)
        product.sync_inventory_from_batches()
        assert product.reduce_quantity(Decimal("3")) is True
        undated.refresh_from_db()
        assert undated.quantity == Decimal("5.000")

    def test_expired_batch_cannot_be_sold_specific_or_fifo(
        self, retailer, category
    ):
        product = _make_batched_product(retailer, category, name="Expired Milk")
        expired = _make_batch(product, "EXP", 10, expiry=_today() - timedelta(days=1))
        fresh = _make_batch(product, "FRESH", 4, expiry=_today() + timedelta(days=7))
        product.sync_inventory_from_batches()

        assert expired.is_expired() is True
        assert product.can_order_quantity(Decimal("4")) is True
        assert product.can_order_quantity(Decimal("5")) is False
        assert product.can_order_quantity(Decimal("1"), batch=expired) is False

        assert product.reduce_quantity(Decimal("1"), batch=expired) is False
        expired.refresh_from_db()
        assert expired.quantity == Decimal("10.000")

        assert product.reduce_quantity(Decimal("4")) is True
        expired.refresh_from_db()
        fresh.refresh_from_db()
        assert expired.quantity == Decimal("10.000")
        assert fresh.quantity == Decimal("0.000")

        assert product.reduce_quantity(Decimal("1")) is False
        expired.refresh_from_db()
        assert expired.quantity == Decimal("10.000")

    def test_allow_negative_does_not_consume_expired(
        self, retailer, category
    ):
        product = _make_batched_product(retailer, category, name="Neg Milk")
        expired = _make_batch(product, "EXP", 5, expiry=_today() - timedelta(days=2))
        product.sync_inventory_from_batches()
        assert product.reduce_quantity(
            Decimal("1"), allow_negative=True
        ) is False
        expired.refresh_from_db()
        assert expired.quantity == Decimal("5.000")

    def test_fifo_reduce_query_budget(
        self, retailer, category, django_assert_num_queries
    ):
        product = _make_batched_product(retailer, category, name="Q Milk")
        _make_batch(product, "SOON", 5, expiry=_today() + timedelta(days=2))
        _make_batch(product, "LATER", 5, expiry=_today() + timedelta(days=20))
        _make_batch(product, "NULL", 5, expiry=None)
        product.sync_inventory_from_batches()

        with django_assert_num_queries(8):
            assert product.reduce_quantity(Decimal("7")) is True


@pytest.mark.django_db
class TestExpiryRbacAndTenancy:
    def test_owner_can_set_and_read_expiry(self, api_client):
        owner, shop = _make_retailer("oe136_own_ok", "OE136 Owner Shop")
        category = _make_category(shop, "OE136 Owner Cat")
        product = _make_batched_product(shop, category, name="Owner Milk")
        batch = _make_batch(product, "B1", 10, expiry=None)
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        expiry = (_today() + timedelta(days=14)).isoformat()
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {
                "has_batches": True,
                "batches": [
                    {
                        "id": batch.id,
                        "quantity": 10,
                        "price": "50.00",
                        "expiry_date": expiry,
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        batch.refresh_from_db()
        assert batch.expiry_date.isoformat() == expiry
        batches = response.data.get("batches") or []
        assert any(row.get("expiry_date") == expiry for row in batches)

    def test_cashier_cannot_mutate_expiry(self, api_client):
        owner, shop = _make_retailer("oe136_own_den", "OE136 Deny Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe136_cashier_den", [])
        cashier_shop = _make_location_profile(cashier, org, "OE136 Cashier Loc")
        category = _make_category(cashier_shop, "OE136 Deny Cat")
        product = _make_batched_product(cashier_shop, category, name="Deny Milk")
        batch = _make_batch(product, "B1", 10, expiry=None)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {
                "has_batches": True,
                "batches": [
                    {
                        "id": batch.id,
                        "quantity": 10,
                        "expiry_date": (_today() + timedelta(days=3)).isoformat(),
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        batch.refresh_from_db()
        assert batch.expiry_date is None

    def test_cashier_echo_expiry_can_patch_price(self, api_client):
        owner, shop = _make_retailer("oe136_own_echo", "OE136 Echo Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe136_cashier_echo", [])
        cashier_shop = _make_location_profile(cashier, org, "OE136 Echo Loc")
        category = _make_category(cashier_shop, "OE136 Echo Cat")
        product = _make_batched_product(cashier_shop, category, name="Echo Milk")
        stored = _today() + timedelta(days=9)
        batch = _make_batch(product, "B1", 10, expiry=stored)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {
                "has_batches": True,
                "price": "44.00",
                "batches": [
                    {
                        "id": batch.id,
                        "quantity": 10,
                        "price": "44.00",
                        "expiry_date": stored.isoformat(),
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        batch.refresh_from_db()
        product.refresh_from_db()
        assert batch.expiry_date == stored
        assert product.price == Decimal("44.00")

    def test_staff_with_adjust_can_set_expiry(self, api_client):
        owner, shop = _make_retailer("oe136_own_staff", "OE136 Staff Shop")
        org = shop.organization
        staff = _make_staff(org, "oe136_adj_staff", [PERM_INVENTORY_ADJUST])
        staff_shop = _make_location_profile(staff, org, "OE136 Staff Loc")
        category = _make_category(staff_shop, "OE136 Staff Cat")
        product = _make_batched_product(staff_shop, category, name="Staff Milk")
        batch = _make_batch(product, "B1", 6, expiry=None)

        api_client.force_authenticate(user=staff)
        expiry = (_today() + timedelta(days=21)).isoformat()
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {
                "has_batches": True,
                "batches": [
                    {"id": batch.id, "quantity": 6, "expiry_date": expiry}
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        batch.refresh_from_db()
        assert batch.expiry_date.isoformat() == expiry

    def test_customer_cannot_mutate_expiry(self, api_client, customer):
        owner, shop = _make_retailer("oe136_own_cust", "OE136 Cust Shop")
        category = _make_category(shop, "OE136 Cust Cat")
        product = _make_batched_product(shop, category, name="Cust Milk")
        batch = _make_batch(product, "B1", 4, expiry=None)

        api_client.force_authenticate(user=customer)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {
                "has_batches": True,
                "batches": [
                    {
                        "id": batch.id,
                        "expiry_date": (_today() + timedelta(days=1)).isoformat(),
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        batch.refresh_from_db()
        assert batch.expiry_date is None

    def test_cross_tenant_cannot_read_or_mutate_batches(self, api_client):
        owner_a, shop_a = _make_retailer("oe136_ten_a", "OE136 Tenant A")
        category = _make_category(shop_a, "OE136 Ten A Cat")
        product = _make_batched_product(shop_a, category, name="TenA Milk")
        batch = _make_batch(
            product, "B1", 8, expiry=_today() + timedelta(days=4)
        )
        owner_b, _shop_b = _make_retailer("oe136_ten_b", "OE136 Tenant B")

        api_client.force_authenticate(user=owner_b)
        read = api_client.get(reverse("get_product_detail", args=[product.id]))
        assert read.status_code != status.HTTP_200_OK
        assert read.data.get("id") != product.id

        mutate = api_client.patch(
            reverse("update_product", args=[product.id]),
            {
                "has_batches": True,
                "batches": [
                    {
                        "id": batch.id,
                        "expiry_date": (_today() + timedelta(days=40)).isoformat(),
                    }
                ],
            },
            format="json",
        )
        assert mutate.status_code == status.HTTP_404_NOT_FOUND
        batch.refresh_from_db()
        assert batch.expiry_date == _today() + timedelta(days=4)

    def test_owner_expiry_patch_query_budget(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("oe136_own_q", "OE136 Queries Shop")
        category = _make_category(shop, "OE136 Q Cat")
        product = _make_batched_product(shop, category, name="Query Milk")
        batch = _make_batch(product, "B1", 3, expiry=None)
        api_client.force_authenticate(user=owner)

        with django_assert_num_queries(24):
            response = api_client.patch(
                reverse("update_product", args=[product.id]),
                {
                    "has_batches": True,
                    "batches": [
                        {
                            "id": batch.id,
                            "quantity": 3,
                            "expiry_date": (_today() + timedelta(days=6)).isoformat(),
                        }
                    ],
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestExpirySalePaths:
    def test_pos_fifo_skips_expired_and_uses_earliest(
        self, api_client
    ):
        owner, shop = _make_retailer("oe136_pos_own", "OE136 POS Shop")
        category = _make_category(shop, "OE136 POS Cat")
        product = _make_batched_product(shop, category, name="POS Milk")
        expired = _make_batch(product, "EXP", 10, expiry=_today() - timedelta(days=1))
        soon = _make_batch(product, "SOON", 10, expiry=_today() + timedelta(days=3))
        later = _make_batch(product, "LATER", 10, expiry=_today() + timedelta(days=30))
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("6")),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        expired.refresh_from_db()
        soon.refresh_from_db()
        later.refresh_from_db()
        assert expired.quantity == Decimal("10.000")
        assert soon.quantity == Decimal("4.000")
        assert later.quantity == Decimal("10.000")

    def test_pos_explicit_expired_batch_is_blocked(self, api_client):
        owner, shop = _make_retailer("oe136_pos_exp", "OE136 POS Exp Shop")
        category = _make_category(shop, "OE136 POS Exp Cat")
        product = _make_batched_product(shop, category, name="POS Exp Milk")
        expired = _make_batch(product, "EXP", 10, expiry=_today() - timedelta(days=1))
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("1"), batch=expired),
            format="json",
        )
        assert response.status_code != status.HTTP_201_CREATED
        expired.refresh_from_db()
        assert expired.quantity == Decimal("10.000")
        assert not Order.objects.filter(retailer=shop, source="pos").exists()

    def test_pos_null_expiry_still_sells(self, api_client):
        owner, shop = _make_retailer("oe136_pos_null", "OE136 POS Null Shop")
        category = _make_category(shop, "OE136 POS Null Cat")
        product = _make_batched_product(shop, category, name="POS Null Milk")
        undated = _make_batch(product, "NULL", 7, expiry=None)
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("2")),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        undated.refresh_from_db()
        assert undated.quantity == Decimal("5.000")

    def test_cross_tenant_cannot_pos_sell_batch(self, api_client):
        owner_a, shop_a = _make_retailer("oe136_pos_a", "OE136 POS A")
        category = _make_category(shop_a, "OE136 POS A Cat")
        product = _make_batched_product(shop_a, category, name="POSA Milk")
        batch = _make_batch(product, "B1", 5, expiry=_today() + timedelta(days=8))
        product.sync_inventory_from_batches()
        owner_b, shop_b = _make_retailer("oe136_pos_b", "OE136 POS B")

        api_client.force_authenticate(user=owner_b)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("1"), batch=batch),
            format="json",
        )
        assert response.status_code != status.HTTP_201_CREATED
        batch.refresh_from_db()
        assert batch.quantity == Decimal("5.000")
        assert not Order.objects.filter(retailer=shop_a, source="pos").exists()
        assert not Order.objects.filter(retailer=shop_b, source="pos").exists()

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_fifo_skips_expired(
        self, mock_silent, mock_push, api_client, customer, address
    ):
        owner, shop = _make_retailer("oe136_chk_own", "OE136 Checkout Shop")
        category = _make_category(shop, "OE136 Checkout Cat")
        product = _make_batched_product(shop, category, name="Chk Milk")
        expired = _make_batch(product, "EXP", 10, expiry=_today() - timedelta(days=3))
        soon = _make_batch(product, "SOON", 10, expiry=_today() + timedelta(days=2))
        product.sync_inventory_from_batches()
        customer.is_phone_verified = True
        customer.save(update_fields=["is_phone_verified"])
        cart = Cart.objects.create(customer=customer, retailer=shop)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=Decimal("3.000"),
            unit_price=product.price,
        )

        api_client.force_authenticate(user=customer)
        response = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": shop.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "address_id": address.id,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        expired.refresh_from_db()
        soon.refresh_from_db()
        assert expired.quantity == Decimal("10.000")
        assert soon.quantity == Decimal("7.000")
