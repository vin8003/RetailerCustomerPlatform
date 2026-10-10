"""
OE-298 / F follow-on — discounted_price on retailer search.

Same Product.discounted_price as list/detail (property = price).
POS no_page uses `discounted_price or price`; that is Decimal-equal
because the property returns price. Product.price is required, so a
persisted SKU never has a null discounted_price. Public search shares
the serializer (channel mixin rewrites the field when present).
Auth/tenancy unchanged. READ only.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBrand, ProductCategory
from products.serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    ProductSearchSerializer,
)
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8902981111111"
PRIMARY_B = "8902982222222"
STORE_ATTA = Decimal("20.00")
STORE_BISCUITS = Decimal("35.50")
APP_ATTA = Decimal("18.00")
MRP_ATTA = Decimal("25.50")
MRP_BISCUITS = Decimal("40.00")
GROUP_ATTA = "oe298-atta"
GROUP_BISCUITS = "oe298-biscuits"


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


def _make_brand(name):
    return ProductBrand.objects.create(name=name, is_active=True)


def _make_product(retailer, category, name, brand=None, barcode=None, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "brand": brand,
        "barcode": barcode,
        "price": Decimal("20.00"),
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _pos(api_client):
    return api_client.get(reverse("get_retailer_products"), {"no_page": "true"})


def _list(api_client):
    return api_client.get(reverse("get_retailer_products"))


def _detail(api_client, product_id):
    return api_client.get(reverse("get_product_detail", args=[product_id]))


def _search(api_client, query):
    return api_client.get(reverse("search_products"), {"search": query})


def _retailer_ctx(user):
    return {
        "request": SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, user_type="retailer")
        )
    }


@pytest.mark.django_db
class TestSearchDiscountedPrice:
    def test_search_discounted_price_matches_list_detail_and_pos(self, api_client):
        owner, shop = _make_retailer("oe298_hit_own", "OE298 Price Shop")
        groceries = _make_category(shop, "OE298 Groceries")
        snacks = _make_category(shop, "OE298 Snacks")
        aashirvaad = _make_brand("OE298 Aashirvaad")
        britannia = _make_brand("OE298 Britannia")
        atta = _make_product(
            shop,
            groceries,
            "OE298 Atta",
            brand=aashirvaad,
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            app_price=APP_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            product_group=GROUP_ATTA,
        )
        biscuits = _make_product(
            shop,
            snacks,
            "OE298 Biscuits",
            brand=britannia,
            barcode=PRIMARY_B,
            price=STORE_BISCUITS,
            original_price=MRP_BISCUITS,
            is_seasonal=False,
            product_group=GROUP_BISCUITS,
        )

        api_client.force_authenticate(user=owner)
        listed = _list(api_client)
        pos = _pos(api_client)
        search = _search(api_client, "OE298")
        atta_detail = _detail(api_client, atta.id)
        biscuits_detail = _detail(api_client, biscuits.id)

        assert listed.status_code == status.HTTP_200_OK
        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert atta_detail.status_code == status.HTTP_200_OK
        assert biscuits_detail.status_code == status.HTTP_200_OK

        for product, expected, detail in (
            (atta, "20.00", atta_detail.data),
            (biscuits, "35.50", biscuits_detail.data),
        ):
            list_row = _row_by_id(listed.data, product.id)
            search_row = _row_by_id(search.data, product.id)
            pos_row = _row_by_id(pos.data, product.id)
            assert "discounted_price" in search_row
            assert search_row["discounted_price"] == expected
            assert search_row["discounted_price"] == list_row["discounted_price"]
            # POS no_page keeps model Decimal on APIClient.data; serializers echo string.
            assert Decimal(str(search_row["discounted_price"])) == Decimal(
                str(pos_row["discounted_price"])
            )
            assert search_row["discounted_price"] == detail["discounted_price"]
            assert search_row["discounted_price"] == list_row["price"]
            # Store channel: app override must not replace search discounted_price.
            if product.id == atta.id:
                assert search_row["app_price"] == "18.00"
                assert search_row["discounted_price"] != search_row["app_price"]
            # OE-287 / OE-290 / OE-291 / OE-293 / OE-294 / OE-295 light non-regression.
            assert search_row["brand_name"] == list_row["brand_name"]
            assert search_row["brand_name"] == pos_row["brand_name"]
            assert search_row["barcode"] == list_row["barcode"]
            assert search_row["barcode"] == pos_row["barcode"]
            assert search_row["category_name"] == list_row["category_name"]
            assert search_row["category_name"] == pos_row["category_name"]
            assert search_row["original_price"] == list_row["original_price"]
            assert Decimal(str(search_row["original_price"])) == Decimal(
                str(pos_row["original_price"])
            )
            assert search_row["is_seasonal"] == list_row["is_seasonal"]
            assert search_row["is_seasonal"] == pos_row["is_seasonal"]
            assert search_row["product_group"] == list_row["product_group"]
            assert search_row["product_group"] == pos_row["product_group"]

    def test_null_discounted_price_mirrors_list_detail(self, monkeypatch):
        """If the property is null, list/detail still emit channel selling price.

        ChannelPriceRepresentationMixin rewrites `discounted_price` to the
        channel selling price. Search must match list/detail. Product.price
        is required on persisted rows, so this is an in-memory override only.
        """
        owner, shop = _make_retailer("oe298_null_own", "OE298 Null Shop")
        category = _make_category(shop, "OE298 Null Cat")
        loose = _make_product(shop, category, "OE298 Loose Rice", barcode=None)
        assert loose.price is not None
        assert loose.discounted_price == loose.price

        ctx = _retailer_ctx(owner)
        monkeypatch.setattr(Product, "discounted_price", property(lambda _self: None))
        loose_refreshed = Product.objects.get(pk=loose.pk)
        assert loose_refreshed.discounted_price is None
        list_data = ProductListSerializer(loose_refreshed, context=ctx).data
        detail_data = ProductDetailSerializer(loose_refreshed, context=ctx).data
        search_data = ProductSearchSerializer(loose_refreshed, context=ctx).data
        assert "discounted_price" in search_data
        assert search_data["discounted_price"] == list_data["discounted_price"]
        assert search_data["discounted_price"] == detail_data["discounted_price"]
        # Mixin surfaces store selling price; do not omit the key.
        assert search_data["discounted_price"] == "20.00"
        assert Decimal(str(search_data["discounted_price"])) == loose_refreshed.price

    def test_public_search_discounted_price_matches_public_list(self, api_client):
        _owner, shop = _make_retailer("oe298_pub_own", "OE298 Public Shop")
        category = _make_category(shop, "OE298 Public Cat")
        branded = _make_product(
            shop,
            category,
            "OE298 Public Milk",
            brand=_make_brand("OE298 Public Brand"),
            barcode=PRIMARY_A,
            price=STORE_ATTA,
            app_price=APP_ATTA,
            original_price=MRP_ATTA,
            is_seasonal=True,
            product_group=GROUP_ATTA,
        )
        loose = _make_product(
            shop,
            category,
            "OE298 Public Loose",
            barcode=None,
            price=STORE_BISCUITS,
            original_price=None,
            is_seasonal=False,
            product_group=None,
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        public_search = api_client.get(
            reverse("search_products_public", args=[shop.id]),
            {"search": "OE298 Public"},
        )
        assert public.status_code == status.HTTP_200_OK
        assert public_search.status_code == status.HTTP_200_OK

        branded_list = _row_by_id(public.data, branded.id)
        branded_search = _row_by_id(public_search.data, branded.id)
        loose_list = _row_by_id(public.data, loose.id)
        loose_search = _row_by_id(public_search.data, loose.id)
        assert "discounted_price" in branded_search
        assert "discounted_price" in loose_search
        assert branded_search["discounted_price"] == branded_list["discounted_price"]
        # Public / app channel rewrites selling price to app_price when set.
        assert branded_search["discounted_price"] == "18.00"
        assert branded_search["price"] == "18.00"
        assert "app_price" not in branded_search
        assert loose_search["discounted_price"] == loose_list["discounted_price"]
        assert loose_search["discounted_price"] == "35.50"
        # Shared serializer still echoes OE-287 / OE-290 / OE-291 / OE-293 / OE-294 / OE-295.
        assert branded_search["brand_name"] == branded_list["brand_name"]
        assert branded_search["barcode"] == branded_list["barcode"] == PRIMARY_A
        assert branded_search["category_name"] == branded_list["category_name"]
        assert branded_search["original_price"] == branded_list["original_price"]
        assert branded_search["is_seasonal"] == branded_list["is_seasonal"] is True
        assert branded_search["product_group"] == branded_list["product_group"] == GROUP_ATTA

    def test_unauthenticated_and_customer_denied(self, api_client):
        _owner, shop = _make_retailer("oe298_auth_own", "OE298 Auth Shop")
        category = _make_category(shop, "OE298 Auth Cat")
        _make_product(
            shop,
            category,
            "OE298 Auth Rice",
            barcode=PRIMARY_A,
            product_group=GROUP_ATTA,
        )
        customer = _make_customer("oe298_auth_cust")

        anon_search = _search(api_client, "OE298")
        assert anon_search.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_search = _search(api_client, "OE298")
        assert cust_search.status_code == status.HTTP_403_FORBIDDEN

    def test_search_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe298_ten_a", "OE298 Tenant A")
        owner_b, shop_b = _make_retailer("oe298_ten_b", "OE298 Tenant B")
        cat_a = _make_category(shop_a, "OE298 A Cat")
        cat_b = _make_category(shop_b, "OE298 B Cat")
        product_a = _make_product(
            shop_a,
            cat_a,
            "OE298 A SKU",
            brand=_make_brand("OE298 Brand A"),
            price=STORE_ATTA,
            product_group=GROUP_ATTA,
        )
        product_b = _make_product(
            shop_b,
            cat_b,
            "OE298 B SKU",
            brand=_make_brand("OE298 Brand B"),
            price=STORE_BISCUITS,
            product_group=GROUP_BISCUITS,
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        search = _search(api_client, "OE298")
        detail_a = _detail(api_client, product_a.id)

        assert pos.status_code == status.HTTP_200_OK
        assert search.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        pos_ids = {row["id"] for row in pos.data}
        search_ids = {row["id"] for row in search.data["results"]}
        assert product_a.id not in pos_ids
        assert product_a.id not in search_ids
        assert product_b.id in pos_ids
        assert product_b.id in search_ids
        assert _row_by_id(search.data, product_b.id)["discounted_price"] == "35.50"
        assert Decimal(str(_row_by_id(pos.data, product_b.id)["discounted_price"])) == (
            STORE_BISCUITS
        )
