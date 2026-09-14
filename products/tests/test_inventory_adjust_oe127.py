"""
OE-127 / F-0028 (thin slice): reject free-form on-hand quantity unless
the caller has inventory.adjust. Sale/purchase dual-write is unchanged.
"""
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.admin import ProductInventoryLogAdmin
from products.inventory_adjust import (
    PERM_INVENTORY_ADJUST,
    bulk_items_set_on_hand_quantity,
    bulk_items_would_change_on_hand,
    payload_sets_on_hand_quantity,
    submitted_on_hand_differs,
)
from retailers.permissions_catalog import ALL_PERMISSION_CODES, ROLE_SLUG_ADMIN, ROLE_SLUG_CASHIER
from products.models import Product, ProductBatch, ProductCategory, ProductInventoryLog
from retailers.models import OrgRole, OrgStaffMembership, RetailerProfile
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


def _make_product(retailer, name="Gate Rice", quantity=50):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=retailer)
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal("90.00"),
        quantity=quantity,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="kg",
    )


class TestOnHandPayloadHelpers:
    def test_product_quantity_key_is_detected(self):
        assert payload_sets_on_hand_quantity({"quantity": 10}) is True
        assert payload_sets_on_hand_quantity({"price": "9.00"}) is False

    def test_batch_quantity_key_is_detected(self):
        assert payload_sets_on_hand_quantity(
            {"batches": [{"id": 1, "quantity": 4}]}
        ) is True
        assert payload_sets_on_hand_quantity(
            {"batches": [{"id": 1, "price": "9.00"}]}
        ) is False

    def test_batch_quantity_json_string_is_detected(self):
        assert payload_sets_on_hand_quantity(
            {"batches": '[{"id": 1, "quantity": 2}]'}
        ) is True

    def test_bulk_items_detect_quantity(self):
        assert bulk_items_set_on_hand_quantity(
            [{"id": 1, "price": "8.00"}, {"id": 2, "quantity": 3}]
        ) is True
        assert bulk_items_set_on_hand_quantity(
            [{"id": 1, "price": "8.00"}]
        ) is False

    def test_echoed_quantity_is_not_a_change(self):
        product = type("P", (), {"quantity": Decimal("50.000")})()
        assert submitted_on_hand_differs(product, {"quantity": 50}) is False
        assert submitted_on_hand_differs(product, {"quantity": "50.000"}) is False
        assert submitted_on_hand_differs(product, {"quantity": 51}) is True
        assert submitted_on_hand_differs(product, {"price": "9.00"}) is False

    def test_bulk_echo_is_not_a_change(self):
        product = type("P", (), {"quantity": Decimal("15.000")})()
        assert bulk_items_would_change_on_hand(
            [{"id": 1, "quantity": 15}], {1: product}
        ) is False
        assert bulk_items_would_change_on_hand(
            [{"id": 1, "quantity": 16}], {1: product}
        ) is True


@pytest.mark.django_db
class TestInventoryAdjustGate:
    def test_cashier_with_location_cannot_patch_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_locden", "OE127 Loc Deny Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe127_cashier_locden", [])
        cashier_shop = _make_location_profile(cashier, org, "OE127 Cashier Deny Loc")
        product = _make_product(cashier_shop, name="Loc Deny Rice", quantity=50)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 999, "price": "88.00"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        product.refresh_from_db()
        assert product.quantity == 50
        assert product.price == Decimal("90.00")

    def test_cashier_echoing_current_quantity_can_patch_price(self, api_client):
        owner, shop = _make_retailer("oe127_own_echo", "OE127 Echo Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe127_cashier_echo", [])
        cashier_shop = _make_location_profile(cashier, org, "OE127 Echo Loc")
        product = _make_product(cashier_shop, name="Echo Rice", quantity=50)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 50, "price": "88.00"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.quantity == 50
        assert product.price == Decimal("88.00")

    def test_cashier_cannot_patch_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_den", "OE127 Deny Shop")
        product = _make_product(shop, quantity=50)
        org = shop.organization
        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        cashier = _make_staff(org, "oe127_cashier_den", cashier_role.permissions)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 999},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Inventory adjust" in response.data["error"]
        product.refresh_from_db()
        assert product.quantity == 50
        assert not ProductInventoryLog.objects.filter(
            product=product, reason="Product update"
        ).exists()

    def test_owner_can_patch_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_ok", "OE127 Owner Shop")
        product = _make_product(shop, quantity=50)

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 80},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.quantity == 80
        log = ProductInventoryLog.objects.filter(
            product=product, reason="Product update"
        ).last()
        assert log is not None
        assert log.quantity_change == 30

    def test_staff_with_inventory_adjust_can_patch_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_staff", "OE127 Staff Shop")
        org = shop.organization
        staff = _make_staff(org, "oe127_adj_staff", [PERM_INVENTORY_ADJUST])
        staff_shop = _make_location_profile(staff, org, "OE127 Staff Location")
        product = _make_product(staff_shop, name="Staff Rice", quantity=20)

        api_client.force_authenticate(user=staff)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 35},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.quantity == 35

    def test_cashier_can_patch_price_without_adjust(self, api_client):
        owner, shop = _make_retailer("oe127_own_price", "OE127 Price Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe127_cashier_price", [])
        cashier_shop = _make_location_profile(cashier, org, "OE127 Cashier Loc")
        product = _make_product(cashier_shop, name="Price Rice", quantity=12)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"price": "77.00"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.price == Decimal("77.00")
        assert product.quantity == 12

    def test_cashier_cannot_hand_set_batch_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_batch", "OE127 Batch Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe127_cashier_batch", [])
        cashier_shop = _make_location_profile(cashier, org, "OE127 Batch Loc")
        product = _make_product(cashier_shop, name="Batch Rice", quantity=10)
        product.has_batches = True
        product.save(update_fields=["has_batches"])
        batch = ProductBatch.objects.create(
            product=product,
            retailer=cashier_shop,
            batch_number="B1",
            price=product.price,
            quantity=10,
            is_active=True,
        )

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {
                "has_batches": True,
                "batches": [{"id": batch.id, "quantity": 99, "price": "90.00"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        batch.refresh_from_db()
        product.refresh_from_db()
        assert batch.quantity == 10
        assert product.quantity == 10

    def test_cross_tenant_quantity_patch_leaves_source_unchanged(self, api_client):
        owner_a, shop_a = _make_retailer("oe127_ten_a", "OE127 Tenant A")
        product = _make_product(shop_a, name="Tenant A Rice", quantity=40)
        owner_b, _shop_b = _make_retailer("oe127_ten_b", "OE127 Tenant B")

        api_client.force_authenticate(user=owner_b)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        product.refresh_from_db()
        assert product.quantity == 40

    def test_stale_admin_role_can_still_adjust_after_bootstrap(self, api_client):
        owner, shop = _make_retailer("oe127_own_stale", "OE127 Stale Admin Shop")
        org = shop.organization
        admin_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_ADMIN)
        admin_role.permissions = [
            code for code in ALL_PERMISSION_CODES if code != PERM_INVENTORY_ADJUST
        ]
        admin_role.save(update_fields=["permissions", "updated_at"])
        staff = User.objects.create_user(
            username="oe127_stale_admin",
            email="oe127_stale_admin@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        OrgStaffMembership.objects.create(
            organization=org, user=staff, role=admin_role, is_active=True
        )
        staff_shop = _make_location_profile(staff, org, "OE127 Stale Loc")
        product = _make_product(staff_shop, name="Stale Rice", quantity=11)

        api_client.force_authenticate(user=staff)
        response = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 14},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.quantity == 14
        admin_role.refresh_from_db()
        assert PERM_INVENTORY_ADJUST in admin_role.permissions

    def test_cashier_cannot_bulk_set_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_bulk", "OE127 Bulk Shop")
        product = _make_product(shop, name="Bulk Rice", quantity=15)
        org = shop.organization
        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        cashier = _make_staff(org, "oe127_cashier_bulk", cashier_role.permissions)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": product.id, "quantity": 400}]},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        product.refresh_from_db()
        assert product.quantity == 15
        assert not RetailerProfile.objects.filter(user=cashier).exists()

    def test_cashier_location_cannot_bulk_set_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_bulkloc", "OE127 Bulk Loc Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe127_cashier_bulkloc", [])
        cashier_shop = _make_location_profile(cashier, org, "OE127 Bulk Loc")
        product = _make_product(cashier_shop, name="Bulk Loc Rice", quantity=15)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": product.id, "quantity": 400}]},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        product.refresh_from_db()
        assert product.quantity == 15

    def test_cashier_bulk_price_only_succeeds(self, api_client):
        owner, shop = _make_retailer("oe127_own_bprice", "OE127 Bulk Price Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe127_cashier_bprice", [])
        cashier_shop = _make_location_profile(cashier, org, "OE127 Bulk Price Loc")
        product = _make_product(cashier_shop, name="Bulk Price Rice", quantity=15)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": product.id, "price": "71.00"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.price == Decimal("71.00")
        assert product.quantity == 15

    def test_mixed_bulk_quantity_applies_nothing(self, api_client):
        owner, shop = _make_retailer("oe127_own_mixed", "OE127 Mixed Bulk Shop")
        org = shop.organization
        cashier = _make_staff(org, "oe127_cashier_mixed", [])
        cashier_shop = _make_location_profile(cashier, org, "OE127 Mixed Loc")
        priced = _make_product(cashier_shop, name="Mixed Price Rice", quantity=8)
        qty_item = _make_product(cashier_shop, name="Mixed Qty Rice", quantity=9)

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("bulk_update_products"),
            {
                "items": [
                    {"id": priced.id, "price": "60.00"},
                    {"id": qty_item.id, "quantity": 90},
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        priced.refresh_from_db()
        qty_item.refresh_from_db()
        assert priced.price == Decimal("90.00")
        assert qty_item.quantity == 9

    def test_owner_can_bulk_set_quantity(self, api_client):
        owner, shop = _make_retailer("oe127_own_bulkok", "OE127 Bulk OK Shop")
        product = _make_product(shop, name="Bulk OK Rice", quantity=15)

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": product.id, "quantity": 22, "price": "81.00"}]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.quantity == 22
        assert product.price == Decimal("81.00")

    def test_owner_quantity_patch_query_budget(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("oe127_own_q", "OE127 Queries Shop")
        product = _make_product(shop, quantity=50)
        api_client.force_authenticate(user=owner)

        # Owner path: profile+org JOIN, select_for_update product, inventory
        # log insert, offer prefetch, and ProductDetailSerializer reads.
        with django_assert_num_queries(20):
            response = api_client.patch(
                reverse("update_product", args=[product.id]),
                {"quantity": 51},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestInventoryLogAdminReadonly:
    def test_admin_cannot_add_change_or_delete(self):
        admin = ProductInventoryLogAdmin(ProductInventoryLog, AdminSite())
        request = type("Req", (), {"user": None})()
        assert admin.has_add_permission(request) is False
        assert admin.has_change_permission(request) is False
        assert admin.has_delete_permission(request) is False
