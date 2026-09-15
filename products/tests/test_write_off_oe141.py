"""
OE-141 / F-0032 — damage / expiry / spoilage write-off (thin EXTEND).

Decreases Product / ProductBatch on-hand under lock, posts ProductInventoryLog
with a reason code, rejects expiry write-off on non-expired lots, gates with
inventory.adjust, filters the existing ledger by reason, and denies tenancy.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from products.inventory_adjust import PERM_INVENTORY_ADJUST
from products.models import Product, ProductBatch, ProductCategory, ProductInventoryLog
from products.write_off import (
    REASON_DAMAGE,
    REASON_EXPIRY,
    REASON_SPOILAGE,
    WriteOffError,
    parse_write_off_quantity,
    write_off_stock,
)
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
    )


def _make_product(retailer, name="Writeoff Rice", quantity=20, has_batches=False):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=retailer)
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal("40.00"),
        quantity=quantity,
        has_batches=has_batches,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="kg",
    )


def _make_batch(product, number, quantity, expiry=None):
    return ProductBatch.objects.create(
        product=product,
        retailer=product.retailer,
        batch_number=number,
        price=product.price,
        quantity=quantity,
        is_active=True,
        expiry_date=expiry,
    )


class TestWriteOffHelpers:
    def test_parse_quantity_rejects_zero_and_negative(self):
        assert parse_write_off_quantity("2.5") == Decimal("2.5")
        assert parse_write_off_quantity(0) is None
        assert parse_write_off_quantity("-1") is None
        assert parse_write_off_quantity("nope") is None

    def test_parse_batch_id_omitted_or_invalid(self):
        from products.write_off import parse_write_off_batch_id

        assert parse_write_off_batch_id(None) is None
        assert parse_write_off_batch_id("") is None
        assert parse_write_off_batch_id("12") == 12
        assert parse_write_off_batch_id("x") is False


@pytest.mark.django_db
class TestWriteOffStock:
    def test_damage_decreases_batch_and_posts_log(self):
        owner, shop = _make_retailer("oe141_own_dmg", "OE141 Damage Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(product, "B1", Decimal("10.000"))
        product.sync_inventory_from_batches()

        log = write_off_stock(
            product_id=product.id,
            retailer=shop,
            quantity=Decimal("3.000"),
            reason=REASON_DAMAGE,
            batch_id=batch.id,
            created_by=owner,
        )

        batch.refresh_from_db()
        product.refresh_from_db()
        assert batch.quantity == Decimal("7.000")
        assert product.quantity == Decimal("7.000")
        assert log.log_type == "damaged"
        assert log.reason == REASON_DAMAGE
        assert log.quantity_change == Decimal("3.000")
        assert log.previous_quantity == Decimal("10.000")
        assert log.new_quantity == Decimal("7.000")
        assert log.batch_id == batch.id
        assert log.created_by_id == owner.id

    def test_spoilage_decreases_simple_product_qty(self):
        owner, shop = _make_retailer("oe141_own_spoil", "OE141 Spoil Shop")
        product = _make_product(shop, quantity=Decimal("8.000"))

        log = write_off_stock(
            product_id=product.id,
            retailer=shop,
            quantity=Decimal("2.000"),
            reason=REASON_SPOILAGE,
            created_by=owner,
        )

        product.refresh_from_db()
        assert product.quantity == Decimal("6.000")
        assert log.log_type == "spoiled"
        assert log.reason == REASON_SPOILAGE
        assert log.batch_id is None
        assert log.previous_quantity == Decimal("8.000")
        assert log.new_quantity == Decimal("6.000")

    def test_expiry_write_off_on_expired_batch(self):
        owner, shop = _make_retailer("oe141_own_expok", "OE141 Exp Ok Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(
            product, "EXP", Decimal("5.000"), expiry=_today() - timedelta(days=1)
        )
        product.sync_inventory_from_batches()

        log = write_off_stock(
            product_id=product.id,
            retailer=shop,
            quantity=Decimal("5.000"),
            reason=REASON_EXPIRY,
            batch_id=batch.id,
            created_by=owner,
        )

        batch.refresh_from_db()
        product.refresh_from_db()
        assert batch.quantity == Decimal("0.000")
        assert product.quantity == Decimal("0.000")
        assert log.log_type == "expired"
        assert log.reason == REASON_EXPIRY

    def test_expiry_write_off_rejects_non_expired_batch(self):
        owner, shop = _make_retailer("oe141_own_expno", "OE141 Exp No Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(
            product, "FRESH", Decimal("5.000"), expiry=_today() + timedelta(days=4)
        )
        product.sync_inventory_from_batches()

        with pytest.raises(WriteOffError) as exc:
            write_off_stock(
                product_id=product.id,
                retailer=shop,
                quantity=Decimal("1.000"),
                reason=REASON_EXPIRY,
                batch_id=batch.id,
                created_by=owner,
            )

        assert exc.value.status_code == 400
        assert "non-expired" in exc.value.message.lower()
        batch.refresh_from_db()
        product.refresh_from_db()
        assert batch.quantity == Decimal("5.000")
        assert product.quantity == Decimal("5.000")
        assert not ProductInventoryLog.objects.filter(product=product).exists()

    def test_expiry_write_off_rejects_null_expiry_batch(self):
        owner, shop = _make_retailer("oe141_own_expnull", "OE141 Exp Null Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(product, "NONE", Decimal("4.000"), expiry=None)
        product.sync_inventory_from_batches()

        with pytest.raises(WriteOffError) as exc:
            write_off_stock(
                product_id=product.id,
                retailer=shop,
                quantity=Decimal("1.000"),
                reason=REASON_EXPIRY,
                batch_id=batch.id,
                created_by=owner,
            )

        assert exc.value.status_code == 400
        batch.refresh_from_db()
        assert batch.quantity == Decimal("4.000")

    def test_batched_product_requires_batch_id(self):
        owner, shop = _make_retailer("oe141_own_needb", "OE141 Need Batch Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        _make_batch(product, "B1", Decimal("3.000"))
        product.sync_inventory_from_batches()

        with pytest.raises(WriteOffError) as exc:
            write_off_stock(
                product_id=product.id,
                retailer=shop,
                quantity=Decimal("1.000"),
                reason=REASON_DAMAGE,
                created_by=owner,
            )

        assert exc.value.status_code == 400
        assert "batch" in exc.value.message.lower()

    def test_quantity_over_on_hand_is_rejected(self):
        owner, shop = _make_retailer("oe141_own_over", "OE141 Over Shop")
        product = _make_product(shop, quantity=Decimal("2.000"))

        with pytest.raises(WriteOffError) as exc:
            write_off_stock(
                product_id=product.id,
                retailer=shop,
                quantity=Decimal("3.000"),
                reason=REASON_DAMAGE,
                created_by=owner,
            )

        assert exc.value.status_code == 400
        product.refresh_from_db()
        assert product.quantity == Decimal("2.000")

    def test_unknown_reason_is_rejected(self):
        owner, shop = _make_retailer("oe141_own_badrsn", "OE141 Bad Reason Shop")
        product = _make_product(shop, quantity=Decimal("2.000"))

        with pytest.raises(WriteOffError) as exc:
            write_off_stock(
                product_id=product.id,
                retailer=shop,
                quantity=Decimal("1.000"),
                reason="theft",
                created_by=owner,
            )

        assert exc.value.status_code == 400
        product.refresh_from_db()
        assert product.quantity == Decimal("2.000")

    def test_cross_tenant_product_is_not_found(self):
        owner_a, shop_a = _make_retailer("oe141_own_a", "OE141 Shop A")
        owner_b, shop_b = _make_retailer("oe141_own_b", "OE141 Shop B")
        product_b = _make_product(shop_b, quantity=Decimal("9.000"))

        with pytest.raises(WriteOffError) as exc:
            write_off_stock(
                product_id=product_b.id,
                retailer=shop_a,
                quantity=Decimal("1.000"),
                reason=REASON_DAMAGE,
                created_by=owner_a,
            )

        assert exc.value.status_code == 404
        product_b.refresh_from_db()
        assert product_b.quantity == Decimal("9.000")

    def test_write_off_query_budget(self, django_assert_num_queries):
        owner, shop = _make_retailer("oe141_own_q", "OE141 Queries Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(product, "Q1", Decimal("6.000"))
        product.sync_inventory_from_batches()

        # SAVEPOINT + lock product + lock batch + update batch + update
        # product + insert log + RELEASE SAVEPOINT.
        with django_assert_num_queries(7):
            write_off_stock(
                product_id=product.id,
                retailer=shop,
                quantity=Decimal("1.000"),
                reason=REASON_DAMAGE,
                batch_id=batch.id,
                created_by=owner,
            )


def _write_off_url(product_id):
    return reverse("write_off_product", args=[product_id])


@pytest.mark.django_db
class TestWriteOffApi:
    def test_owner_can_write_off_damage(self, api_client):
        owner, shop = _make_retailer("oe141_api_own", "OE141 API Owner Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(product, "API1", Decimal("10.000"))
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        response = api_client.post(
            _write_off_url(product.id),
            {"quantity": "4.000", "reason": REASON_DAMAGE, "batch_id": batch.id},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["reason"] == REASON_DAMAGE
        assert response.data["log_type"] == "damaged"
        batch.refresh_from_db()
        product.refresh_from_db()
        assert batch.quantity == Decimal("6.000")
        assert product.quantity == Decimal("6.000")

    def test_expiry_write_off_rejects_fresh_batch(self, api_client):
        owner, shop = _make_retailer("oe141_api_fresh", "OE141 API Fresh Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(
            product, "FRESH", Decimal("8.000"), expiry=_today() + timedelta(days=2)
        )
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        response = api_client.post(
            _write_off_url(product.id),
            {"quantity": "1", "reason": REASON_EXPIRY, "batch_id": batch.id},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "non-expired" in response.data["error"].lower()
        batch.refresh_from_db()
        assert batch.quantity == Decimal("8.000")

    def test_cashier_without_adjust_gets_403(self, api_client):
        owner, shop = _make_retailer("oe141_api_den", "OE141 API Deny Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe141_cashier_den", [])
        cashier_shop = _make_location_profile(cashier, org, "OE141 Cashier Deny Loc")
        product = _make_product(cashier_shop, quantity=Decimal("12.000"))

        api_client.force_authenticate(user=cashier)
        response = api_client.post(
            _write_off_url(product.id),
            {"quantity": "1", "reason": REASON_DAMAGE},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        product.refresh_from_db()
        assert product.quantity == Decimal("12.000")
        assert not ProductInventoryLog.objects.filter(product=product).exists()

    def test_staff_with_inventory_adjust_can_write_off(self, api_client):
        owner, shop = _make_retailer("oe141_api_staff", "OE141 API Staff Shop")
        org = shop.organization
        staff = _make_staff(org, "oe141_adj_staff", [PERM_INVENTORY_ADJUST])
        staff_shop = _make_location_profile(staff, org, "OE141 Staff Loc")
        product = _make_product(staff_shop, quantity=Decimal("9.000"))

        api_client.force_authenticate(user=staff)
        response = api_client.post(
            _write_off_url(product.id),
            {"quantity": "2", "reason": REASON_SPOILAGE},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        product.refresh_from_db()
        assert product.quantity == Decimal("7.000")

    def test_customer_is_forbidden(self, api_client, customer):
        owner, shop = _make_retailer("oe141_api_cust", "OE141 API Cust Shop")
        product = _make_product(shop, quantity=Decimal("5.000"))

        api_client.force_authenticate(user=customer)
        response = api_client.post(
            _write_off_url(product.id),
            {"quantity": "1", "reason": REASON_DAMAGE},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        product.refresh_from_db()
        assert product.quantity == Decimal("5.000")

    def test_unauthenticated_is_401(self, api_client):
        owner, shop = _make_retailer("oe141_api_anon", "OE141 API Anon Shop")
        product = _make_product(shop, quantity=Decimal("5.000"))

        response = api_client.post(
            _write_off_url(product.id),
            {"quantity": "1", "reason": REASON_DAMAGE},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_write_off_is_404(self, api_client):
        owner_a, shop_a = _make_retailer("oe141_api_ten_a", "OE141 API Tenant A")
        product = _make_product(shop_a, quantity=Decimal("11.000"))
        owner_b, _shop_b = _make_retailer("oe141_api_ten_b", "OE141 API Tenant B")

        api_client.force_authenticate(user=owner_b)
        response = api_client.post(
            _write_off_url(product.id),
            {"quantity": "1", "reason": REASON_DAMAGE},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        product.refresh_from_db()
        assert product.quantity == Decimal("11.000")

    def test_owner_write_off_query_budget(self, api_client, django_assert_num_queries):
        owner, shop = _make_retailer("oe141_api_q", "OE141 API Queries Shop")
        product = _make_product(shop, has_batches=True, quantity=0)
        batch = _make_batch(product, "AQ1", Decimal("6.000"))
        product.sync_inventory_from_batches()

        api_client.force_authenticate(user=owner)
        # Profile+org JOIN; owner perm is implicit; write_off_stock is 7
        # including savepoints.
        with django_assert_num_queries(8):
            response = api_client.post(
                _write_off_url(product.id),
                {
                    "quantity": "1.000",
                    "reason": REASON_DAMAGE,
                    "batch_id": batch.id,
                },
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED


def _ledger_url():
    return reverse("get_inventory_ledger")


@pytest.mark.django_db
class TestWriteOffLedgerFilter:
    def test_ledger_filters_by_reason(self, api_client):
        owner, shop = _make_retailer("oe141_led_own", "OE141 Ledger Shop")
        product = _make_product(shop, quantity=Decimal("20.000"))
        write_off_stock(
            product_id=product.id,
            retailer=shop,
            quantity=Decimal("2.000"),
            reason=REASON_DAMAGE,
            created_by=owner,
        )
        write_off_stock(
            product_id=product.id,
            retailer=shop,
            quantity=Decimal("1.000"),
            reason=REASON_SPOILAGE,
            created_by=owner,
        )
        ProductInventoryLog.objects.create(
            product=product,
            log_type="added",
            quantity_change=Decimal("5.000"),
            previous_quantity=Decimal("17.000"),
            new_quantity=Decimal("22.000"),
            reason="Product update",
            created_by=owner,
        )

        api_client.force_authenticate(user=owner)
        response = api_client.get(
            _ledger_url(),
            {"product_id": product.id, "reason": REASON_DAMAGE},
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["reason"] == REASON_DAMAGE
        assert response.data[0]["log_type"] == "damaged"
        assert "batch_id" in response.data[0]

    def test_shop_wide_reason_filter_hides_other_tenant(self, api_client):
        owner_a, shop_a = _make_retailer("oe141_led_a", "OE141 Ledger A")
        owner_b, shop_b = _make_retailer("oe141_led_b", "OE141 Ledger B")
        product_a = _make_product(shop_a, name="A Rice", quantity=Decimal("10.000"))
        product_b = _make_product(shop_b, name="B Rice", quantity=Decimal("10.000"))
        write_off_stock(
            product_id=product_a.id,
            retailer=shop_a,
            quantity=Decimal("1.000"),
            reason=REASON_DAMAGE,
            created_by=owner_a,
        )
        write_off_stock(
            product_id=product_b.id,
            retailer=shop_b,
            quantity=Decimal("3.000"),
            reason=REASON_DAMAGE,
            created_by=owner_b,
        )

        api_client.force_authenticate(user=owner_a)
        response = api_client.get(_ledger_url(), {"reason": REASON_DAMAGE})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert str(response.data[0]["quantity_change"]) in ("1.000", "1.0", "1")

    def test_cross_tenant_product_ledger_is_404(self, api_client):
        owner_a, shop_a = _make_retailer("oe141_led_ten_a", "OE141 Led Ten A")
        product = _make_product(shop_a, quantity=Decimal("4.000"))
        write_off_stock(
            product_id=product.id,
            retailer=shop_a,
            quantity=Decimal("1.000"),
            reason=REASON_DAMAGE,
            created_by=owner_a,
        )
        owner_b, _shop_b = _make_retailer("oe141_led_ten_b", "OE141 Led Ten B")

        api_client.force_authenticate(user=owner_b)
        response = api_client.get(
            _ledger_url(),
            {"product_id": product.id, "reason": REASON_DAMAGE},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_ledger_requires_product_or_reason(self, api_client):
        owner, _shop = _make_retailer("oe141_led_req", "OE141 Ledger Req")
        api_client.force_authenticate(user=owner)
        response = api_client.get(_ledger_url())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
