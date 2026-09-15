"""
OE-106 / F-0023 — store vs owned-app price isolation (thin EXTEND).

POS reads store ``price``. Customer/app reads ``app_price`` or store fallback.
Cart charges the app list. One ATP pool. No marketplace connector.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from cart.models import Cart, CartItem
from products.channel_price import CHANNEL_APP, CHANNEL_STORE
from products.models import Product, ProductCategory
from retailers.models import RetailerProfile
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
