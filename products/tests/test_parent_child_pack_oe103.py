"""
OE-103 / F-0021 — parent-child pack SKUs (thin EXTEND).

Sale conversion already lives on Product.reduce_quantity. This file locks
that path plus factor-0, cycle reject, inventory.adjust on pack-link
mutations, existing parent/child sell, and cross-tenant deny.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError

from authentication.models import User
from cart.models import Cart, CartItem
from orders.models import Order
from products.inventory_adjust import (
    PERM_INVENTORY_ADJUST,
    create_payload_sets_pack_link,
    payload_sets_pack_link,
    submitted_pack_link_differs,
)
from products.models import Product, ProductCategory
from products.serializers import (
    ProductCreateSerializer,
    ProductUpdateSerializer,
    parent_bulk_cycle_exists,
)
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


def _make_parent_child(retailer, category, prefix="Pack"):
    parent = Product.objects.create(
        retailer=retailer,
        name=f"{prefix} Rice 50kg",
        category=category,
        price=Decimal("2000.00"),
        quantity=Decimal("10.000"),
        track_inventory=True,
        is_active=True,
        is_available=True,
        is_parent_bulk=True,
        unit="kg",
    )
    child = Product.objects.create(
        retailer=retailer,
        name=f"{prefix} Rice 5kg",
        category=category,
        price=Decimal("250.00"),
        quantity=Decimal("0.000"),
        track_inventory=True,
        is_active=True,
        is_available=True,
        parent_bulk_product=parent,
        conversion_factor=Decimal("0.1000"),
        unit="kg",
    )
    parent.refresh_from_db()
    child.refresh_from_db()
    return parent, child


def _pos_payload(product, quantity):
    qty = Decimal(str(quantity))
    unit = Decimal(str(product.price))
    line_total = unit * qty
    return {
        "payment_mode": "cash",
        "subtotal": float(line_total),
        "total_amount": float(line_total),
        "items": [
            {
                "product_id": product.id,
                "quantity": float(qty),
                "unit_price": float(unit),
            }
        ],
    }


class TestPackLinkHelpers:
    def test_payload_detects_pack_fields(self):
        assert payload_sets_pack_link({"conversion_factor": "0.1"}) is True
        assert payload_sets_pack_link({"parent_bulk_product": 3}) is True
        assert payload_sets_pack_link({"is_parent_bulk": True}) is True
        assert payload_sets_pack_link({"price": "9.00"}) is False

    def test_echoed_factor_is_not_a_change(self):
        product = type(
            "P",
            (),
            {
                "conversion_factor": Decimal("0.1000"),
                "is_parent_bulk": False,
                "parent_bulk_product_id": 9,
            },
        )()
        assert submitted_pack_link_differs(
            product, {"conversion_factor": "0.1000"}
        ) is False
        assert submitted_pack_link_differs(
            product, {"conversion_factor": "0.2000"}
        ) is True
        assert submitted_pack_link_differs(
            product, {"parent_bulk_product": 9}
        ) is False
        assert submitted_pack_link_differs(
            product, {"parent_bulk_product": 8}
        ) is True

    def test_create_payload_defaults_are_not_pack_links(self):
        assert create_payload_sets_pack_link({"name": "Rice", "price": "10"}) is False
        assert create_payload_sets_pack_link({"is_parent_bulk": False}) is False
        assert create_payload_sets_pack_link({"conversion_factor": "0.1"}) is True
        assert create_payload_sets_pack_link({"is_parent_bulk": True}) is True


@pytest.mark.django_db
class TestConversionFactorAndCycle:
    def test_update_rejects_conversion_factor_zero(self, retailer, category):
        parent, child = _make_parent_child(retailer, category, prefix="Zero")
        serializer = ProductUpdateSerializer(
            instance=child,
            data={"conversion_factor": "0"},
            partial=True,
            context={"retailer": retailer},
        )
        with pytest.raises(DRFValidationError) as excinfo:
            serializer.is_valid(raise_exception=True)
        err = str(excinfo.value).lower()
        assert "0.0001" in err or "greater than zero" in err

    def test_create_rejects_conversion_factor_zero(self, retailer, category):
        parent = Product.objects.create(
            retailer=retailer,
            name="Zero Create Parent",
            category=category,
            price=Decimal("100.00"),
            quantity=Decimal("10.000"),
            is_parent_bulk=True,
            track_inventory=True,
        )
        serializer = ProductCreateSerializer(
            data={
                "name": "Zero Create Child",
                "price": "10.00",
                "category": category.id,
                "parent_bulk_product": parent.id,
                "conversion_factor": "0",
            },
            context={"retailer": retailer},
        )
        assert serializer.is_valid() is False
        assert "conversion_factor" in serializer.errors

    def test_update_rejects_self_parent_cycle(self, retailer, category):
        standalone = Product.objects.create(
            retailer=retailer,
            name="Cycle Self",
            category=category,
            price=Decimal("10.00"),
            quantity=Decimal("5.000"),
            track_inventory=True,
        )
        serializer = ProductUpdateSerializer(
            instance=standalone,
            data={
                "parent_bulk_product": standalone.id,
                "conversion_factor": "1.0000",
            },
            partial=True,
            context={"retailer": retailer},
        )
        with pytest.raises(DRFValidationError) as excinfo:
            serializer.is_valid(raise_exception=True)
        assert "cycle" in str(excinfo.value).lower()

    def test_parent_bulk_cycle_helper_detects_loop(self, retailer, category):
        a = Product.objects.create(
            retailer=retailer,
            name="Cycle A",
            category=category,
            price=Decimal("10.00"),
            quantity=Decimal("5.000"),
        )
        b = Product.objects.create(
            retailer=retailer,
            name="Cycle B",
            category=category,
            price=Decimal("10.00"),
            quantity=Decimal("5.000"),
            parent_bulk_product=a,
            conversion_factor=Decimal("1.0000"),
        )
        # ORM-only back pointer (serializers also reject "both parent and child").
        Product.objects.filter(pk=a.pk).update(parent_bulk_product=b)
        a.refresh_from_db()
        assert parent_bulk_cycle_exists(b.pk, a) is True
        assert parent_bulk_cycle_exists(a.pk, a) is True


@pytest.mark.django_db
class TestPackLinkRbacAndTenancy:
    def test_cashier_cannot_change_conversion_factor(self, api_client):
        owner, shop = _make_retailer("oe103_own_den", "OE103 Deny Shop")
        category = _make_category(shop, "OE103 Deny Cat")
        parent, child = _make_parent_child(shop, category, prefix="Deny")
        org = shop.organization
        cashier = _make_staff(org, "oe103_cashier_den", [])
        cashier_shop = _make_location_profile(cashier, org, "OE103 Cashier Deny Loc")
        Product.objects.filter(pk__in=[parent.pk, child.pk]).update(
            retailer=cashier_shop
        )
        child.refresh_from_db()

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[child.id]),
            {"conversion_factor": "0.2000", "price": "240.00"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Inventory adjust" in response.data["error"]
        child.refresh_from_db()
        assert child.conversion_factor == Decimal("0.1000")
        assert child.price == Decimal("250.00")

    def test_cashier_echoing_factor_can_patch_price(self, api_client):
        owner, shop = _make_retailer("oe103_own_echo", "OE103 Echo Shop")
        category = _make_category(shop, "OE103 Echo Cat")
        parent, child = _make_parent_child(shop, category, prefix="Echo")
        org = shop.organization
        cashier = _make_staff(org, "oe103_cashier_echo", [])
        cashier_shop = _make_location_profile(cashier, org, "OE103 Echo Loc")
        Product.objects.filter(pk__in=[parent.pk, child.pk]).update(
            retailer=cashier_shop
        )
        child.refresh_from_db()

        api_client.force_authenticate(user=cashier)
        response = api_client.patch(
            reverse("update_product", args=[child.id]),
            {"conversion_factor": "0.1000", "price": "240.00"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        child.refresh_from_db()
        assert child.conversion_factor == Decimal("0.1000")
        assert child.price == Decimal("240.00")

    def test_cashier_cannot_create_child_pack(self, api_client):
        owner, shop = _make_retailer("oe103_own_create", "OE103 Create Shop")
        category = _make_category(shop, "OE103 Create Cat")
        parent, _child = _make_parent_child(shop, category, prefix="CreateGate")
        org = shop.organization
        cashier = _make_staff(org, "oe103_cashier_create", [])
        cashier_shop = _make_location_profile(cashier, org, "OE103 Create Loc")
        loc_category = _make_category(cashier_shop, "OE103 Create Loc Cat")
        loc_parent = Product.objects.create(
            retailer=cashier_shop,
            name="Create Loc Parent",
            category=loc_category,
            price=Decimal("100.00"),
            quantity=Decimal("10.000"),
            is_parent_bulk=True,
            track_inventory=True,
            is_active=True,
            is_available=True,
        )

        api_client.force_authenticate(user=cashier)
        response = api_client.post(
            reverse("create_product"),
            {
                "name": "Create Loc Child",
                "category": loc_category.id,
                "price": "10.00",
                "parent_bulk_product": loc_parent.id,
                "conversion_factor": "0.1000",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Product.objects.filter(
            retailer=cashier_shop, name="Create Loc Child"
        ).exists()

    def test_owner_can_change_conversion_factor(self, api_client):
        owner, shop = _make_retailer("oe103_own_ok", "OE103 Owner Shop")
        category = _make_category(shop, "OE103 Owner Cat")
        parent, child = _make_parent_child(shop, category, prefix="Owner")

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            reverse("update_product", args=[child.id]),
            {"conversion_factor": "0.2000"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        child.refresh_from_db()
        assert child.conversion_factor == Decimal("0.2000")

    def test_staff_with_inventory_adjust_can_change_factor(self, api_client):
        owner, shop = _make_retailer("oe103_own_staff", "OE103 Staff Shop")
        org = shop.organization
        staff = _make_staff(org, "oe103_adj_staff", [PERM_INVENTORY_ADJUST])
        staff_shop = _make_location_profile(staff, org, "OE103 Staff Loc")
        category = _make_category(staff_shop, "OE103 Staff Cat")
        parent, child = _make_parent_child(staff_shop, category, prefix="Staff")

        api_client.force_authenticate(user=staff)
        response = api_client.patch(
            reverse("update_product", args=[child.id]),
            {"conversion_factor": "0.2500"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        child.refresh_from_db()
        assert child.conversion_factor == Decimal("0.2500")

    def test_customer_cannot_change_conversion_factor(self, api_client, customer):
        owner, shop = _make_retailer("oe103_own_cust", "OE103 Cust Shop")
        category = _make_category(shop, "OE103 Cust Cat")
        parent, child = _make_parent_child(shop, category, prefix="Cust")

        api_client.force_authenticate(user=customer)
        response = api_client.patch(
            reverse("update_product", args=[child.id]),
            {"conversion_factor": "0.5000"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        child.refresh_from_db()
        assert child.conversion_factor == Decimal("0.1000")

    def test_cross_tenant_cannot_mutate_factor(self, api_client):
        owner_a, shop_a = _make_retailer("oe103_ten_a", "OE103 Tenant A")
        category = _make_category(shop_a, "OE103 Ten A Cat")
        parent, child = _make_parent_child(shop_a, category, prefix="TenA")
        owner_b, _shop_b = _make_retailer("oe103_ten_b", "OE103 Tenant B")

        api_client.force_authenticate(user=owner_b)
        response = api_client.patch(
            reverse("update_product", args=[child.id]),
            {"conversion_factor": "0.9000"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        child.refresh_from_db()
        assert child.conversion_factor == Decimal("0.1000")

    def test_cross_tenant_cannot_read_pack_product(self, api_client):
        owner_a, shop_a = _make_retailer("oe103_read_a", "OE103 Read A")
        category = _make_category(shop_a, "OE103 Read A Cat")
        parent, child = _make_parent_child(shop_a, category, prefix="ReadA")
        owner_b, _shop_b = _make_retailer("oe103_read_b", "OE103 Read B")

        api_client.force_authenticate(user=owner_b)
        response = api_client.get(reverse("get_product_detail", args=[child.id]))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data.get("id") != child.id
        assert "conversion_factor" not in response.data

    def test_cannot_point_parent_at_other_tenant_product(self, api_client):
        owner_a, shop_a = _make_retailer("oe103_ptr_a", "OE103 Ptr A")
        cat_a = _make_category(shop_a, "OE103 Ptr A Cat")
        standalone = Product.objects.create(
            retailer=shop_a,
            name="Ptr Child",
            category=cat_a,
            price=Decimal("10.00"),
            quantity=Decimal("0.000"),
            track_inventory=True,
            is_active=True,
            is_available=True,
        )
        owner_b, shop_b = _make_retailer("oe103_ptr_b", "OE103 Ptr B")
        cat_b = _make_category(shop_b, "OE103 Ptr B Cat")
        foreign_parent = Product.objects.create(
            retailer=shop_b,
            name="Ptr Foreign Parent",
            category=cat_b,
            price=Decimal("100.00"),
            quantity=Decimal("10.000"),
            is_parent_bulk=True,
            track_inventory=True,
        )

        api_client.force_authenticate(user=owner_a)
        response = api_client.patch(
            reverse("update_product", args=[standalone.id]),
            {
                "parent_bulk_product": foreign_parent.id,
                "conversion_factor": "0.1000",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        standalone.refresh_from_db()
        assert standalone.parent_bulk_product_id is None

    def test_bulk_update_ignores_conversion_factor(self, api_client):
        owner, shop = _make_retailer("oe103_own_bulk", "OE103 Bulk Shop")
        category = _make_category(shop, "OE103 Bulk Cat")
        parent, child = _make_parent_child(shop, category, prefix="Bulk")

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            reverse("bulk_update_products"),
            {
                "items": [
                    {
                        "id": child.id,
                        "price": "240.00",
                        "conversion_factor": "0.9000",
                    }
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        child.refresh_from_db()
        assert child.conversion_factor == Decimal("0.1000")
        assert child.price == Decimal("240.00")

    def test_owner_pack_link_patch_query_budget(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("oe103_own_q", "OE103 Queries Shop")
        category = _make_category(shop, "OE103 Q Cat")
        parent, child = _make_parent_child(shop, category, prefix="Query")
        api_client.force_authenticate(user=owner)

        with django_assert_num_queries(23):
            response = api_client.patch(
                reverse("update_product", args=[child.id]),
                {"conversion_factor": "0.2000"},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestChildSaleAdjustsParent:
    def test_pos_child_sale_adjusts_parent_by_factor(self, api_client):
        owner, shop = _make_retailer("oe103_pos_own", "OE103 POS Shop")
        category = _make_category(shop, "OE103 POS Cat")
        parent, child = _make_parent_child(shop, category, prefix="POS")

        api_client.force_authenticate(user=owner)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(child, Decimal("10")),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        parent.refresh_from_db()
        child.refresh_from_db()
        # 10 child units * 0.10 = 1 parent bag
        assert parent.quantity == Decimal("9.000")
        assert child.quantity == Decimal("90.000")
        assert Order.objects.filter(retailer=shop, source="pos").exists()

    def test_pos_parent_sale_still_works(self, api_client):
        owner, shop = _make_retailer("oe103_pos_par", "OE103 POS Parent Shop")
        category = _make_category(shop, "OE103 POS Parent Cat")
        parent, child = _make_parent_child(shop, category, prefix="POSPar")

        api_client.force_authenticate(user=owner)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(parent, Decimal("1")),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        parent.refresh_from_db()
        child.refresh_from_db()
        assert parent.quantity == Decimal("9.000")
        assert child.quantity == Decimal("90.000")

    def test_pos_child_sale_query_budget(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("oe103_pos_q", "OE103 POS Q Shop")
        category = _make_category(shop, "OE103 POS Q Cat")
        parent, child = _make_parent_child(shop, category, prefix="POSQ")
        api_client.force_authenticate(user=owner)

        # One lock_for_sale for sold child + pack parent (pk ASC), not ad-hoc child-then-parent.
        with django_assert_num_queries(33):
            response = api_client.post(
                reverse("create_pos_order"),
                _pos_payload(child, Decimal("10")),
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_checkout_child_sale_adjusts_parent(
        self, mock_silent, mock_push, api_client, customer, address
    ):
        owner, shop = _make_retailer("oe103_chk_own", "OE103 Checkout Shop")
        category = _make_category(shop, "OE103 Checkout Cat")
        parent, child = _make_parent_child(shop, category, prefix="Chk")
        customer.is_phone_verified = True
        customer.save(update_fields=["is_phone_verified"])
        cart = Cart.objects.create(customer=customer, retailer=shop)
        CartItem.objects.create(
            cart=cart,
            product=child,
            quantity=Decimal("10.000"),
            unit_price=child.price,
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
        parent.refresh_from_db()
        child.refresh_from_db()
        assert parent.quantity == Decimal("9.000")
        assert child.quantity == Decimal("90.000")

    def test_cross_tenant_cannot_pos_sell_child(self, api_client):
        owner_a, shop_a = _make_retailer("oe103_pos_a", "OE103 POS A")
        category = _make_category(shop_a, "OE103 POS A Cat")
        parent, child = _make_parent_child(shop_a, category, prefix="POSA")
        owner_b, shop_b = _make_retailer("oe103_pos_b", "OE103 POS B")

        api_client.force_authenticate(user=owner_b)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(child, Decimal("1")),
            format="json",
        )

        assert response.status_code != status.HTTP_201_CREATED
        parent.refresh_from_db()
        assert parent.quantity == Decimal("10.000")
        assert not Order.objects.filter(retailer=shop_a, source="pos").exists()
        assert not Order.objects.filter(retailer=shop_b, source="pos").exists()
