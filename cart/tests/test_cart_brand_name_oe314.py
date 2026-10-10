"""
OE-314 / F follow-on — brand_name on cart line items.

Same Product.brand.name as list/detail. No brand → null
(mirror list getter). Auth/tenancy unchanged. READ only.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from cart.models import Cart, CartItem
from cart.serializers import CartItemSerializer
from products.models import Product, ProductBrand, ProductCategory
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
        minimum_order_amount=Decimal("1.00"),
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


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_brand(name):
    return ProductBrand.objects.create(name=name, is_active=True)


def _make_product(retailer, category, name, brand=None, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "brand": brand,
        "price": Decimal("20.00"),
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("20.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
        "minimum_order_quantity": 1,
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _add_cart_item(customer, product, quantity=1):
    cart, _created = Cart.objects.get_or_create(
        customer=customer, retailer=product.retailer
    )
    return CartItem.objects.create(
        cart=cart,
        product=product,
        quantity=quantity,
        unit_price=product.price,
    )


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _cart_item_by_product(cart_payload, product_id):
    items = cart_payload.get("items") or []
    for item in items:
        if item["product"] == product_id:
            return item
    raise AssertionError(f"product {product_id} missing from cart items")


def _cart_for_retailer(carts, retailer_id):
    for cart in carts:
        if cart["retailer"] == retailer_id:
            return cart
    raise AssertionError(f"cart for retailer {retailer_id} missing")


def _list(api_client):
    return api_client.get(reverse("get_retailer_products"))


def _detail(api_client, product_id):
    return api_client.get(reverse("get_product_detail", args=[product_id]))


def _public_list(api_client, retailer_id):
    return api_client.get(
        reverse("get_retailer_products_public", args=[retailer_id])
    )


def _public_detail(api_client, retailer_id, product_id):
    return api_client.get(
        reverse("get_product_detail_public", args=[retailer_id, product_id])
    )


def _get_cart(api_client, retailer_id=None):
    params = {"retailer_id": retailer_id} if retailer_id is not None else None
    return api_client.get(reverse("get_cart"), params)


def _brand_pk_lookups(queries):
    hits = []
    for query in queries:
        sql = query["sql"].lower()
        if "from \"product_brand\"" not in sql and "from product_brand" not in sql:
            continue
        if " join " in sql:
            continue
        hits.append(query["sql"])
    return hits


@pytest.mark.django_db
class TestCartItemBrandName:
    def test_cart_brand_name_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe314_hit_own", "OE314 Brand Shop")
        customer = _make_customer("oe314_hit_cust")
        category = _make_category(shop, "OE314 Brand Cat")
        aashirvaad = _make_brand("OE314 Aashirvaad")
        britannia = _make_brand("OE314 Britannia")
        atta = _make_product(shop, category, "OE314 Atta", brand=aashirvaad)
        biscuits = _make_product(shop, category, "OE314 Biscuits", brand=britannia)
        _add_cart_item(customer, atta, quantity=2)
        _add_cart_item(customer, biscuits, quantity=1)

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)
        assert listed.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        api_client.force_authenticate(user=customer)
        cart = _get_cart(api_client, shop.id)
        carts = _get_cart(api_client)
        public = _public_list(api_client, shop.id)
        public_atta = _public_detail(api_client, shop.id, atta.id)
        public_biscuits = _public_detail(api_client, shop.id, biscuits.id)

        assert cart.status_code == status.HTTP_200_OK
        assert carts.status_code == status.HTTP_200_OK
        assert public.status_code == status.HTTP_200_OK
        assert public_atta.status_code == status.HTTP_200_OK
        assert public_biscuits.status_code == status.HTTP_200_OK

        listed_cart = _cart_for_retailer(carts.data, shop.id)
        for product, expected, detail, public_detail in (
            (atta, "OE314 Aashirvaad", atta_detail.data, public_atta.data),
            (biscuits, "OE314 Britannia", biscuits_detail.data, public_biscuits.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            public_row = _row_by_id(public.data, product.id)
            cart_row = _cart_item_by_product(cart.data, product.id)
            listed_row = _cart_item_by_product(listed_cart, product.id)
            assert "brand_name" in cart_row
            assert cart_row["brand_name"] == expected
            assert cart_row["brand_name"] == list_row["brand_name"]
            assert cart_row["brand_name"] == detail["brand_name"]
            assert cart_row["brand_name"] == public_row["brand_name"]
            assert cart_row["brand_name"] == public_detail["brand_name"]
            assert listed_row["brand_name"] == cart_row["brand_name"]

    def test_null_brand_is_null_like_list(self, api_client):
        owner, shop = _make_retailer("oe314_null_own", "OE314 Null Shop")
        customer = _make_customer("oe314_null_cust")
        category = _make_category(shop, "OE314 Null Cat")
        product = _make_product(shop, category, "OE314 Loose Rice", brand=None)
        assert product.brand_id is None
        _add_cart_item(customer, product)

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        detail = _detail(api_client, product.id)
        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK

        api_client.force_authenticate(user=customer)
        cart = _get_cart(api_client, shop.id)
        public = _public_list(api_client, shop.id)
        public_detail = _public_detail(api_client, shop.id, product.id)

        assert cart.status_code == status.HTTP_200_OK
        assert public.status_code == status.HTTP_200_OK
        assert public_detail.status_code == status.HTTP_200_OK

        list_row = _row_by_id(listed.data, product.id)
        public_row = _row_by_id(public.data, product.id)
        cart_row = _cart_item_by_product(cart.data, product.id)
        assert "brand_name" in cart_row
        assert list_row["brand_name"] is None
        assert detail.data["brand_name"] is None
        assert public_row["brand_name"] is None
        assert public_detail.data["brand_name"] is None
        assert cart_row["brand_name"] is None

    def test_serializer_echoes_brand_and_null(self):
        _owner, shop = _make_retailer("oe314_ser_own", "OE314 Serializer Shop")
        customer = _make_customer("oe314_ser_cust")
        category = _make_category(shop, "OE314 Serializer Cat")
        branded = _make_product(
            shop, category, "OE314 Ser Branded", brand=_make_brand("OE314 Ser Brand")
        )
        loose = _make_product(shop, category, "OE314 Ser Loose", brand=None)
        branded_item = _add_cart_item(customer, branded)
        loose_item = _add_cart_item(customer, loose)

        branded_data = CartItemSerializer(branded_item).data
        loose_data = CartItemSerializer(loose_item).data
        assert branded_data["brand_name"] == "OE314 Ser Brand"
        assert loose_data["brand_name"] is None

    def test_unauthenticated_and_retailer_denied(self, api_client):
        _owner, shop = _make_retailer("oe314_auth_own", "OE314 Auth Shop")
        _make_product(
            shop,
            _make_category(shop, "OE314 Auth Cat"),
            "OE314 Auth Rice",
            brand=_make_brand("OE314 Auth Brand"),
        )
        retailer_user = _owner

        anon = _get_cart(api_client, shop.id)
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=retailer_user)
        retailer_cart = _get_cart(api_client, shop.id)
        assert retailer_cart.status_code == status.HTTP_403_FORBIDDEN

    def test_cart_stays_customer_and_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe314_ten_a", "OE314 Tenant A")
        _owner_b, shop_b = _make_retailer("oe314_ten_b", "OE314 Tenant B")
        customer_a = _make_customer("oe314_ten_cust_a")
        customer_b = _make_customer("oe314_ten_cust_b")
        product_a = _make_product(
            shop_a,
            _make_category(shop_a, "OE314 A Cat"),
            "OE314 A SKU",
            brand=_make_brand("OE314 Brand A"),
        )
        product_b = _make_product(
            shop_b,
            _make_category(shop_b, "OE314 B Cat"),
            "OE314 B SKU",
            brand=_make_brand("OE314 Brand B"),
        )
        _add_cart_item(customer_a, product_a)
        _add_cart_item(customer_b, product_b)
        _add_cart_item(customer_a, product_b)

        api_client.force_authenticate(user=customer_b)
        cart_b = _get_cart(api_client, shop_a.id)
        carts_b = _get_cart(api_client)
        assert cart_b.status_code == status.HTTP_200_OK
        assert carts_b.status_code == status.HTTP_200_OK
        assert cart_b.data["items"] == []
        cart_b_ids = {
            item["product"]
            for cart in carts_b.data
            for item in cart["items"]
        }
        assert product_a.id not in cart_b_ids
        shop_b_cart = _cart_for_retailer(carts_b.data, shop_b.id)
        assert _cart_item_by_product(shop_b_cart, product_b.id)["brand_name"] == (
            "OE314 Brand B"
        )

        api_client.force_authenticate(user=customer_a)
        cart_a_shop_a = _get_cart(api_client, shop_a.id)
        assert cart_a_shop_a.status_code == status.HTTP_200_OK
        a_ids = {item["product"] for item in cart_a_shop_a.data["items"]}
        assert product_a.id in a_ids
        assert product_b.id not in a_ids
        assert _cart_item_by_product(cart_a_shop_a.data, product_a.id)[
            "brand_name"
        ] == "OE314 Brand A"

    def test_add_to_cart_response_includes_brand_name(self, api_client):
        _owner, shop = _make_retailer("oe314_add_own", "OE314 Add Shop")
        customer = _make_customer("oe314_add_cust")
        product = _make_product(
            shop,
            _make_category(shop, "OE314 Add Cat"),
            "OE314 Add Milk",
            brand=_make_brand("OE314 Add Brand"),
        )

        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 1},
        )
        assert res.status_code == status.HTTP_201_CREATED
        row = _cart_item_by_product(res.data, product.id)
        assert row["brand_name"] == "OE314 Add Brand"

    def test_cart_join_brand_not_per_row(self, api_client):
        _owner, shop = _make_retailer("oe314_q_own", "OE314 Query Shop")
        customer = _make_customer("oe314_q_cust")
        category = _make_category(shop, "OE314 Query Cat")
        products = []
        for i in range(3):
            brand = _make_brand(f"OE314 Query Brand {i}")
            product = _make_product(
                shop, category, f"OE314 Query SKU {i}", brand=brand
            )
            _add_cart_item(customer, product)
            products.append(product)

        api_client.force_authenticate(user=customer)
        with CaptureQueriesContext(connection) as retailer_ctx:
            cart = _get_cart(api_client, shop.id)
        with CaptureQueriesContext(connection) as list_ctx:
            carts = _get_cart(api_client)

        assert cart.status_code == status.HTTP_200_OK
        assert carts.status_code == status.HTTP_200_OK
        assert _brand_pk_lookups(retailer_ctx.captured_queries) == []
        assert _brand_pk_lookups(list_ctx.captured_queries) == []
        listed_cart = _cart_for_retailer(carts.data, shop.id)
        for product in products:
            expected = product.brand.name
            assert _cart_item_by_product(cart.data, product.id)["brand_name"] == expected
            assert _cart_item_by_product(listed_cart, product.id)["brand_name"] == expected
