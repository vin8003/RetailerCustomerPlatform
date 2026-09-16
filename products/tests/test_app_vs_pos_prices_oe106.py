"""
OE-106 / F-0023 — store vs owned-app price isolation (thin EXTEND).

POS reads store ``price``. Customer/app reads ``app_price`` or store fallback.
Cart charges the app list. One ATP pool. No marketplace connector.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from cart.models import Cart, CartItem
from orders.models import Order, OrderItem
from customers.models import CustomerWishlist
from products.channel_price import CHANNEL_APP, CHANNEL_STORE, PERM_CATALOG_PRICE
from products.models import Product, ProductBatch, ProductCategory
from retailers.models import OrgAuditLog, OrgRole, OrgStaffMembership, RetailerProfile
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


def _make_customer(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
        is_email_verified=True,
    )


def _make_product(retailer, name="OE106 Rice", store="40.00", app=None, quantity=20):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=retailer)
    return Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        price=Decimal(store),
        app_price=None if app is None else Decimal(app),
        quantity=quantity,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="kg",
    )


def _pos_payload(product, unit_price=None, quantity=1):
    unit = float(product.price if unit_price is None else unit_price)
    line_total = unit * quantity
    return {
        "payment_mode": "cash",
        "subtotal": line_total,
        "total_amount": line_total,
        "items": [
            {
                "product_id": product.id,
                "quantity": quantity,
                "unit_price": unit,
            }
        ],
    }


@pytest.mark.django_db
class TestChannelPriceReads:
    def test_retailer_detail_shows_store_and_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_ret_det", "OE106 Retailer Detail")
        product = _make_product(shop, app="33.00")
        api_client.force_authenticate(user=owner)

        resp = api_client.get(reverse("get_product_detail", args=[product.id]))
        assert resp.status_code == status.HTTP_200_OK
        assert Decimal(str(resp.data["price"])) == Decimal("40.00")
        assert Decimal(str(resp.data["app_price"])) == Decimal("33.00")

    def test_public_detail_uses_app_price_and_hides_store_list(self, api_client):
        owner, shop = _make_retailer("oe106_pub_det", "OE106 Public Detail")
        product = _make_product(shop, app="33.00")
        customer = _make_customer("oe106_pub_cust")
        api_client.force_authenticate(user=customer)

        resp = api_client.get(
            reverse(
                "get_product_detail_public",
                kwargs={"retailer_id": shop.id, "product_id": product.id},
            )
        )
        assert resp.status_code == status.HTTP_200_OK
        assert Decimal(str(resp.data["price"])) == Decimal("33.00")
        assert "app_price" not in resp.data

    def test_public_detail_falls_back_when_app_price_null(self, api_client):
        owner, shop = _make_retailer("oe106_pub_fb", "OE106 Public Fallback")
        product = _make_product(shop)
        resp = api_client.get(
            reverse(
                "get_product_detail_public",
                kwargs={"retailer_id": shop.id, "product_id": product.id},
            )
        )
        assert resp.status_code == status.HTTP_200_OK
        assert Decimal(str(resp.data["price"])) == Decimal("40.00")
        assert "app_price" not in resp.data

    def test_pos_no_page_keeps_store_price(self, api_client):
        owner, shop = _make_retailer("oe106_pos_list", "OE106 POS List")
        product = _make_product(shop, app="33.00")
        api_client.force_authenticate(user=owner)

        resp = api_client.get(reverse("get_retailer_products"), {"no_page": "true"})
        assert resp.status_code == status.HTTP_200_OK
        row = next(item for item in resp.data if item["id"] == product.id)
        assert Decimal(str(row["price"])) == Decimal("40.00")
        assert Decimal(str(row["app_price"])) == Decimal("33.00")

    def test_pos_checkout_uses_store_price_not_app(self, api_client):
        owner, shop = _make_retailer("oe106_pos_chk", "OE106 POS Checkout")
        product = _make_product(shop, app="33.00")
        api_client.force_authenticate(user=owner)

        ok = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product),
            format="json",
        )
        assert ok.status_code == status.HTTP_201_CREATED

        mismatch = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, unit_price=Decimal("33.00")),
            format="json",
        )
        assert mismatch.status_code == status.HTTP_400_BAD_REQUEST
        assert "Price mismatch" in str(mismatch.data)

    def test_cart_add_uses_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_cart", "OE106 Cart Shop")
        product = _make_product(shop, app="33.00")
        customer = _make_customer("oe106_cart_cust")
        api_client.force_authenticate(user=customer)

        resp = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 1},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        item = CartItem.objects.get(product=product)
        assert item.unit_price == Decimal("33.00")
        row = resp.data["items"][0]
        assert Decimal(str(row["product_price"])) == Decimal("33.00")
        assert Decimal(str(row["unit_price"])) == Decimal("33.00")

    def test_public_detail_app_price_adds_no_queries(self, api_client):
        owner, shop = _make_retailer("oe106_q_read", "OE106 Read Q Shop")
        product = _make_product(shop)
        url = reverse(
            "get_product_detail_public",
            kwargs={"retailer_id": shop.id, "product_id": product.id},
        )
        api_client.get(url)

        with CaptureQueriesContext(connection) as baseline:
            first = api_client.get(url)
        assert first.status_code == status.HTTP_200_OK

        product.app_price = Decimal("33.00")
        product.save(update_fields=["app_price"])

        with CaptureQueriesContext(connection) as after:
            second = api_client.get(url)
        assert second.status_code == status.HTTP_200_OK
        assert Decimal(str(second.data["price"])) == Decimal("33.00")
        assert len(after) == len(baseline)

    def test_one_atp_pool_unchanged_across_channels(self):
        owner, shop = _make_retailer("oe106_atp", "OE106 ATP Shop")
        product = _make_product(shop, app="33.00", quantity=9)
        assert product.channel_selling_price(CHANNEL_STORE) != product.channel_selling_price(
            CHANNEL_APP
        )
        assert product.quantity == Decimal("9")
        assert Cart.objects.count() == 0

    def test_retailer_search_keeps_store_price_and_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_ret_search", "OE106 Retailer Search")
        product = _make_product(shop, app="33.00")
        api_client.force_authenticate(user=owner)

        resp = api_client.get(reverse("search_products"))
        assert resp.status_code == status.HTTP_200_OK
        row = next(item for item in resp.data["results"] if item["id"] == product.id)
        assert Decimal(str(row["price"])) == Decimal("40.00")
        assert Decimal(str(row["app_price"])) == Decimal("33.00")

    def test_public_search_still_uses_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_pub_search", "OE106 Public Search")
        product = _make_product(shop, app="33.00")

        resp = api_client.get(reverse("search_products_public", args=[shop.id]))
        assert resp.status_code == status.HTTP_200_OK
        row = next(item for item in resp.data["results"] if item["id"] == product.id)
        assert Decimal(str(row["price"])) == Decimal("33.00")
        assert "app_price" not in row

    def test_public_detail_rewrites_batch_and_group_variant_prices(self, api_client):
        owner, shop = _make_retailer("oe106_nested", "OE106 Nested Prices")
        product = _make_product(shop, name="OE106 Group A", app="33.00")
        product.product_group = "oe106-grain"
        product.has_batches = True
        product.save(update_fields=["product_group", "has_batches"])
        ProductBatch.objects.create(
            product=product,
            retailer=shop,
            batch_number="B-OE106",
            price=Decimal("42.00"),
            quantity=4,
            is_active=True,
        )
        sibling = _make_product(shop, name="OE106 Group B", store="80.00", app="70.00")
        sibling.product_group = "oe106-grain"
        sibling.save(update_fields=["product_group"])
        customer = _make_customer("oe106_nested_cust")
        api_client.force_authenticate(user=customer)

        public = api_client.get(
            reverse(
                "get_product_detail_public",
                kwargs={"retailer_id": shop.id, "product_id": product.id},
            )
        )
        assert public.status_code == status.HTTP_200_OK
        assert Decimal(str(public.data["price"])) == Decimal("33.00")
        assert public.data["batches"]
        assert Decimal(str(public.data["batches"][0]["price"])) == Decimal("33.00")
        variant = next(
            row for row in public.data["group_variants"] if row["id"] == sibling.id
        )
        assert Decimal(str(variant["price"])) == Decimal("70.00")
        assert "app_price" not in public.data

        api_client.force_authenticate(user=owner)
        store = api_client.get(reverse("get_product_detail", args=[product.id]))
        assert store.status_code == status.HTTP_200_OK
        assert Decimal(str(store.data["price"])) == Decimal("40.00")
        assert Decimal(str(store.data["batches"][0]["price"])) == Decimal("42.00")
        store_variant = next(
            row for row in store.data["group_variants"] if row["id"] == sibling.id
        )
        assert Decimal(str(store_variant["price"])) == Decimal("80.00")

    def test_wishlist_uses_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_wish", "OE106 Wishlist Shop")
        product = _make_product(shop, app="33.00")
        customer = _make_customer("oe106_wish_cust")
        CustomerWishlist.objects.create(customer=customer, product=product)
        api_client.force_authenticate(user=customer)

        resp = api_client.get(reverse("get_customer_wishlist"))
        assert resp.status_code == status.HTTP_200_OK
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        row = next(item for item in rows if item["product"] == product.id)
        assert Decimal(str(row["product_price"])) == Decimal("33.00")

    def test_wishlist_empty_and_retailer_denied(self, api_client):
        owner, shop = _make_retailer("oe106_wish_neg", "OE106 Wishlist Deny")
        _make_product(shop, app="33.00")
        customer = _make_customer("oe106_wish_empty")
        api_client.force_authenticate(user=customer)
        empty = api_client.get(reverse("get_customer_wishlist"))
        assert empty.status_code == status.HTTP_200_OK
        rows = empty.data["results"] if isinstance(empty.data, dict) else empty.data
        assert rows == []

        api_client.force_authenticate(user=owner)
        denied = api_client.get(reverse("get_customer_wishlist"))
        assert denied.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestChannelPricePlaceOrder:
    def _verified_customer(self, username):
        customer = _make_customer(username)
        customer.is_phone_verified = True
        customer.save(update_fields=["is_phone_verified"])
        return customer

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_stamps_cart_app_unit_price(
        self, mock_silent, mock_push, api_client
    ):
        owner, shop = _make_retailer("oe106_po_shop", "OE106 Place Order Shop")
        product = _make_product(shop, app="33.00")
        customer = self._verified_customer("oe106_po_cust")
        api_client.force_authenticate(user=customer)

        added = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 2},
            format="json",
        )
        assert added.status_code == status.HTTP_201_CREATED
        cart_item = CartItem.objects.get(product=product)
        assert cart_item.unit_price == Decimal("33.00")

        placed = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": shop.id,
                "delivery_mode": "pickup",
                "payment_mode": "cash_pickup",
            },
            format="json",
        )
        assert placed.status_code == status.HTTP_201_CREATED

        order = Order.objects.get(customer=customer, retailer=shop)
        line = OrderItem.objects.get(order=order, product=product)
        assert line.unit_price == Decimal("33.00")
        assert line.product_price == Decimal("33.00")
        assert line.total_price == Decimal("66.00")
        assert line.unit_price != product.price
        assert order.subtotal == Decimal("66.00")
        assert order.total_amount == line.total_price + order.delivery_fee

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_null_app_price_falls_back_to_store(
        self, mock_silent, mock_push, api_client
    ):
        owner, shop = _make_retailer("oe106_po_fb", "OE106 Place Order Fallback")
        product = _make_product(shop)
        customer = self._verified_customer("oe106_po_fb_cust")
        api_client.force_authenticate(user=customer)

        added = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 1},
            format="json",
        )
        assert added.status_code == status.HTTP_201_CREATED

        placed = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": shop.id,
                "delivery_mode": "pickup",
                "payment_mode": "cash_pickup",
            },
            format="json",
        )
        assert placed.status_code == status.HTTP_201_CREATED
        line = OrderItem.objects.get(product=product)
        assert line.unit_price == Decimal("40.00")
        assert line.product_price == Decimal("40.00")


@pytest.mark.django_db
class TestChannelPriceWrites:
    def test_owner_sets_app_price_and_is_audited(self, api_client):
        owner, shop = _make_retailer("oe106_own_set", "OE106 Owner Set")
        product = _make_product(shop)
        api_client.force_authenticate(user=owner)

        resp = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"app_price": "33.00"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.app_price == Decimal("33.00")
        assert product.price == Decimal("40.00")
        row = OrgAuditLog.objects.get(
            organization=shop.organization,
            object_type=OrgAuditLog.OBJECT_CHANNEL_PRICE,
            object_id=str(product.id),
        )
        assert row.action == OrgAuditLog.ACTION_UPDATE
        assert row.summary_before["app_price"] is None
        assert row.summary_after["app_price"] == "33.00"

    def test_cashier_cannot_change_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_csh_deny", "OE106 Cashier Deny")
        cashier = _make_staff(shop.organization, "oe106_csh_deny_u", [])
        loc = _make_location_profile(cashier, shop.organization, "OE106 Cashier Loc")
        product = _make_product(loc, name="Cashier Rice", app="33.00")
        api_client.force_authenticate(user=cashier)

        resp = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"app_price": "31.00"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "Catalog price" in resp.data["error"]
        product.refresh_from_db()
        assert product.app_price == Decimal("33.00")
        assert not OrgAuditLog.objects.filter(
            object_type=OrgAuditLog.OBJECT_CHANNEL_PRICE
        ).exists()

    def test_cashier_echo_app_price_can_patch_name(self, api_client):
        owner, shop = _make_retailer("oe106_csh_echo", "OE106 Cashier Echo")
        cashier = _make_staff(shop.organization, "oe106_csh_echo_u", [])
        loc = _make_location_profile(cashier, shop.organization, "OE106 Echo Loc")
        product = _make_product(loc, name="Echo Rice", app="33.00")
        api_client.force_authenticate(user=cashier)

        resp = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"app_price": "33.00", "name": "Echo Rice Renamed"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.name == "Echo Rice Renamed"
        assert product.app_price == Decimal("33.00")

    def test_staff_with_catalog_price_can_set_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_staff_ok", "OE106 Staff Price")
        staff = _make_staff(
            shop.organization, "oe106_staff_ok_u", [PERM_CATALOG_PRICE]
        )
        loc = _make_location_profile(staff, shop.organization, "OE106 Staff Loc")
        product = _make_product(loc, name="Staff Rice")
        api_client.force_authenticate(user=staff)

        resp = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"app_price": "29.50"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.app_price == Decimal("29.50")

    def test_cross_tenant_app_price_patch_is_404(self, api_client):
        owner_a, shop_a = _make_retailer("oe106_ten_a", "OE106 Tenant A")
        product = _make_product(shop_a, app="33.00")
        owner_b, shop_b = _make_retailer("oe106_ten_b", "OE106 Tenant B")
        api_client.force_authenticate(user=owner_b)

        resp = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"app_price": "1.00"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        product.refresh_from_db()
        assert product.app_price == Decimal("33.00")

    def test_cashier_cannot_bulk_set_app_price(self, api_client):
        owner, shop = _make_retailer("oe106_bulk_csh", "OE106 Bulk Cashier")
        cashier = _make_staff(shop.organization, "oe106_bulk_csh_u", [])
        loc = _make_location_profile(cashier, shop.organization, "OE106 Bulk Loc")
        product = _make_product(loc, name="Bulk Rice")
        api_client.force_authenticate(user=cashier)

        resp = api_client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": product.id, "app_price": "22.00"}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        product.refresh_from_db()
        assert product.app_price is None

    def test_owner_bulk_sets_app_price_and_is_audited(self, api_client):
        owner, shop = _make_retailer("oe106_bulk_own", "OE106 Bulk Owner")
        product = _make_product(shop)
        api_client.force_authenticate(user=owner)

        resp = api_client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": product.id, "app_price": "22.00"}]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.app_price == Decimal("22.00")
        assert OrgAuditLog.objects.filter(
            organization=shop.organization,
            object_type=OrgAuditLog.OBJECT_CHANNEL_PRICE,
            object_id=str(product.id),
        ).exists()

    def test_create_with_app_price_requires_permission(self, api_client):
        owner, shop = _make_retailer("oe106_crt_own", "OE106 Create Shop")
        cashier = _make_staff(shop.organization, "oe106_crt_csh", [])
        _make_location_profile(cashier, shop.organization, "OE106 Create Loc")
        category = ProductCategory.objects.create(
            name="Create Cat", retailer=shop
        )
        api_client.force_authenticate(user=cashier)
        resp = api_client.post(
            reverse("create_product"),
            {
                "name": "New App Priced",
                "price": "40.00",
                "app_price": "33.00",
                "quantity": 1,
                "category": category.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert not Product.objects.filter(name="New App Priced").exists()

    def test_owner_app_price_patch_query_budget(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("oe106_q_write", "OE106 Write Q Shop")
        product = _make_product(shop)
        api_client.force_authenticate(user=owner)

        with django_assert_num_queries(20):
            resp = api_client.patch(
                reverse("update_product", args=[product.id]),
                {"app_price": "33.00"},
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
