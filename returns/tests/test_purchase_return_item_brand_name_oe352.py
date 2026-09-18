"""
OE-352 / F follow-on — optional brand_name on purchase-return line items.

Same Product.brand.name as list/detail when product (and brand) exists.
No product / no brand → null (mirror list getter). Auth/tenancy unchanged.
READ only. Does not touch SalesReturnItemSerializer, ProductSearchSerializer
Meta, or POS views.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db.models import Prefetch
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductBrand, ProductCategory
from retailers.models import RetailerProfile, Supplier
from retailers.organization import ensure_organization_for_profile
from returns.models import PurchaseReturn, PurchaseReturnItem
from returns.serializers import (
    PurchaseReturnItemSerializer,
    PurchaseReturnSerializer,
    SalesReturnItemSerializer,
)


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
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _make_supplier(retailer, company_name):
    return Supplier.objects.create(
        retailer=retailer,
        company_name=company_name,
        contact_person="Test Contact",
        phone_number="9876543210",
    )


def _make_purchase_return(retailer, supplier, created_by, items, notes="OE-352 read echo"):
    purchase_return = PurchaseReturn.objects.create(
        retailer=retailer,
        supplier=supplier,
        notes=notes,
        created_by=created_by,
        total_amount=Decimal("0.00"),
    )
    total = Decimal("0.00")
    created = []
    for product, quantity, purchase_price in items:
        line_total = quantity * purchase_price
        created.append(
            PurchaseReturnItem.objects.create(
                purchase_return=purchase_return,
                product=product,
                quantity=quantity,
                purchase_price=purchase_price,
                total=line_total,
            )
        )
        total += line_total
    purchase_return.total_amount = total
    purchase_return.save(update_fields=["total_amount"])
    return purchase_return, created


def _item_by_product(payload, product_id):
    items = payload.get("items") or []
    for row in items:
        if row["product"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from purchase-return items")


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _return_from_list(payload, return_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == return_id:
            return row
    raise AssertionError(f"purchase return {return_id} missing from payload")


def _brand_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product_brand"' in q["sql"]
    ]


@pytest.mark.django_db
class TestPurchaseReturnItemBrandName:
    def test_item_brand_name_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe352_hit_own", "OE352 Brand Shop")
        category = _make_category(shop, "OE352 Brand Cat")
        brand_a = _make_brand("OE352 Brand A")
        brand_b = _make_brand("OE352 Brand B")
        sku_a = _make_product(shop, category, "OE352 Atta", brand=brand_a)
        sku_b = _make_product(shop, category, "OE352 Oil", brand=brand_b)
        unbranded = _make_product(shop, category, "OE352 Loose", brand=None)
        supplier = _make_supplier(shop, "OE352 Hit Supplier")
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            owner,
            [
                (sku_a, Decimal("1.000"), Decimal("10.00")),
                (sku_b, Decimal("2.000"), Decimal("8.00")),
                (unbranded, Decimal("1.000"), Decimal("5.00")),
            ],
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        detail_a = api_client.get(reverse("get_product_detail", args=[sku_a.id]))
        detail_b = api_client.get(reverse("get_product_detail", args=[sku_b.id]))
        detail_loose = api_client.get(
            reverse("get_product_detail", args=[unbranded.id])
        )
        return_list = api_client.get(reverse("purchase-return-list"))
        return_detail = api_client.get(
            reverse("purchase-return-detail", args=[purchase_return.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_200_OK
        assert detail_b.status_code == status.HTTP_200_OK
        assert detail_loose.status_code == status.HTTP_200_OK
        assert return_list.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK

        list_return = _return_from_list(return_list.data, purchase_return.id)
        for product, expected, detail in (
            (sku_a, "OE352 Brand A", detail_a.data),
            (sku_b, "OE352 Brand B", detail_b.data),
            (unbranded, None, detail_loose.data),
        ):
            catalog = _row_by_id(listed.data, product.id)
            for payload in (return_detail.data, list_return):
                item = _item_by_product(payload, product.id)
                assert "brand_name" in item
                assert item["brand_name"] == expected
                assert item["brand_name"] == catalog["brand_name"]
                assert item["brand_name"] == detail["brand_name"]
                assert item["product_name"] == product.name

    def test_null_brand_stays_null_like_list(self, api_client):
        owner, shop = _make_retailer("oe352_null_own", "OE352 Null Shop")
        category = _make_category(shop, "OE352 Null Cat")
        product = _make_product(shop, category, "OE352 No Brand", brand=None)
        supplier = _make_supplier(shop, "OE352 Null Supplier")
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        return_detail = api_client.get(
            reverse("purchase-return-detail", args=[purchase_return.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK
        item = _item_by_product(return_detail.data, product.id)
        catalog = _row_by_id(listed.data, product.id)
        assert item["brand_name"] is None
        assert item["brand_name"] == catalog["brand_name"]
        assert item["brand_name"] == detail.data["brand_name"]

    def test_missing_product_returns_null_brand(self):
        assert (
            PurchaseReturnItemSerializer().get_brand_name(
                SimpleNamespace(product=None)
            )
            is None
        )

    def test_write_payload_brand_name_is_ignored(self, api_client):
        owner, shop = _make_retailer("oe352_write_own", "OE352 Write Shop")
        category = _make_category(shop, "OE352 Write Cat")
        brand = _make_brand("OE352 Real Brand")
        product = _make_product(shop, category, "OE352 Write Atta", brand=brand)
        supplier = _make_supplier(shop, "OE352 Write Supplier")

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("purchase-return-list"),
            {
                "supplier_id": supplier.id,
                "notes": "OE-352 write ignore",
                "items": [
                    {
                        "product_id": product.id,
                        "quantity": 1,
                        "purchase_price": "10.00",
                        "brand_name": "FAKE BRAND",
                    }
                ],
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        item = _item_by_product(created.data, product.id)
        assert item["brand_name"] == "OE352 Real Brand"
        product.refresh_from_db()
        assert product.brand.name == "OE352 Real Brand"

    def test_unauthenticated_denied(self, api_client):
        owner, shop = _make_retailer("oe352_auth_own", "OE352 Auth Shop")
        category = _make_category(shop, "OE352 Auth Cat")
        brand = _make_brand("OE352 Auth Brand")
        product = _make_product(shop, category, "OE352 Auth Rice", brand=brand)
        supplier = _make_supplier(shop, "OE352 Auth Supplier")
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        listed = api_client.get(reverse("purchase-return-list"))
        detail = api_client.get(
            reverse("purchase-return-detail", args=[purchase_return.id])
        )
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert detail.status_code == status.HTTP_401_UNAUTHORIZED

    def test_return_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("oe352_ten_a", "OE352 Tenant A")
        owner_b, shop_b = _make_retailer("oe352_ten_b", "OE352 Tenant B")
        cat_a = _make_category(shop_a, "OE352 A Cat")
        cat_b = _make_category(shop_b, "OE352 B Cat")
        product_a = _make_product(
            shop_a, cat_a, "OE352 A SKU", brand=_make_brand("OE352 A Brand")
        )
        product_b = _make_product(
            shop_b, cat_b, "OE352 B SKU", brand=_make_brand("OE352 B Brand")
        )
        ret_a, _ = _make_purchase_return(
            shop_a,
            _make_supplier(shop_a, "OE352 A Supplier"),
            owner_a,
            [(product_a, Decimal("1.000"), Decimal("10.00"))],
        )
        ret_b, _ = _make_purchase_return(
            shop_b,
            _make_supplier(shop_b, "OE352 B Supplier"),
            owner_b,
            [(product_b, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("purchase-return-list"))
        foreign = api_client.get(reverse("purchase-return-detail", args=[ret_a.id]))
        own = api_client.get(reverse("purchase-return-detail", args=[ret_b.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert foreign.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in listed.data["results"]}
        assert ret_a.id not in ids
        assert ret_b.id in ids
        assert _item_by_product(own.data, product_b.id)["brand_name"] == "OE352 B Brand"

    def test_sales_return_item_serializer_stays_without_brand_name(self):
        assert "brand_name" not in SalesReturnItemSerializer.Meta.fields

    def test_select_related_brand_adds_no_brand_query(self):
        _owner, shop = _make_retailer("oe352_n1_own", "OE352 N1 Shop")
        category = _make_category(shop, "OE352 N1 Cat")
        products = [
            _make_product(
                shop,
                category,
                f"OE352 N1 {name}",
                brand=_make_brand(f"OE352 N1 {name}"),
            )
            for name in ("Alpha", "Beta", "Gamma")
        ]
        supplier = _make_supplier(shop, "OE352 N1 Supplier")
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            _owner,
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )

        loaded = list(
            PurchaseReturnItem.objects.select_related("product", "product__brand")
            .filter(purchase_return=purchase_return)
            .order_by("id")
        )
        with CaptureQueriesContext(connection) as captured:
            data = PurchaseReturnItemSerializer(loaded, many=True).data

        assert [row["brand_name"] for row in data] == [
            "OE352 N1 Alpha",
            "OE352 N1 Beta",
            "OE352 N1 Gamma",
        ]
        assert _brand_table_reads(captured) == []

    def test_prefetched_return_items_add_no_brand_query(self):
        owner, shop = _make_retailer("oe352_n1c_own", "OE352 N1C Shop")
        category = _make_category(shop, "OE352 N1C Cat")
        brand = _make_brand("OE352 N1C Brand")
        product = _make_product(shop, category, "OE352 N1C Sugar", brand=brand)
        supplier = _make_supplier(shop, "OE352 N1C Supplier")
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        loaded = (
            PurchaseReturn.objects.select_related("supplier", "created_by")
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=PurchaseReturnItem.objects.select_related(
                        "product", "product__brand"
                    ),
                )
            )
            .get(pk=purchase_return.id)
        )

        with CaptureQueriesContext(connection) as captured:
            payload = PurchaseReturnSerializer(loaded).data

        assert _item_by_product(payload, product.id)["brand_name"] == "OE352 N1C Brand"
        assert _brand_table_reads(captured) == []
