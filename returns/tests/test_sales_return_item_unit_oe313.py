"""
OE-313 / F follow-on — top-level unit on sales-return line items.

Same value as list/detail Product.unit. Empty/null stays empty/null
(no invented 'piece' on read). Auth/tenancy unchanged. READ only.
Does not touch ProductSearchSerializer Meta, POS views, customers,
orders serializers, or purchase invoice serializers.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.db.models import Prefetch
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from orders.models import Order, OrderItem
from products.models import Product, ProductCategory
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile
from returns.models import SalesReturn, SalesReturnItem
from returns.serializers import SalesReturnItemSerializer, SalesReturnSerializer


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


def _make_product(retailer, category, name, unit="piece", **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "price": Decimal("20.00"),
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": unit,
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _make_order(retailer, items):
    order = Order.objects.create(
        retailer=retailer,
        guest_name="Walk-in",
        delivery_mode="pickup",
        payment_mode="cash",
        status="delivered",
        source="pos",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    for product, quantity, unit_price in items:
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=quantity,
            unit_price=unit_price,
            total_price=quantity * unit_price,
        )
    return order


def _make_sales_return(retailer, order, created_by, items):
    sales_return = SalesReturn.objects.create(
        retailer=retailer,
        order=order,
        refund_payment_mode="cash",
        reason="OE-313 read echo",
        created_by=created_by,
        refund_amount=Decimal("0.00"),
    )
    total = Decimal("0.00")
    created = []
    for product, quantity, refund_unit_price in items:
        line_total = quantity * refund_unit_price
        created.append(
            SalesReturnItem.objects.create(
                sales_return=sales_return,
                product=product,
                quantity=quantity,
                refund_unit_price=refund_unit_price,
                total_refund=line_total,
            )
        )
        total += line_total
    sales_return.refund_amount = total
    sales_return.save(update_fields=["refund_amount"])
    return sales_return, created


def _item_by_product(payload, product_id):
    items = payload.get("items") or []
    for row in items:
        if row["product"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from sales-return items")


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
    raise AssertionError(f"sales return {return_id} missing from payload")


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestSalesReturnItemUnit:
    def test_item_unit_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe313_hit_own", "OE313 Unit Shop")
        category = _make_category(shop, "OE313 Unit Cat")
        kg = _make_product(shop, category, "OE313 Atta", unit="kg")
        pack = _make_product(shop, category, "OE313 Biscuits", unit="pack")
        default = _make_product(shop, category, "OE313 Piece Default", unit="piece")
        order = _make_order(
            shop,
            [
                (kg, Decimal("2.000"), Decimal("10.00")),
                (pack, Decimal("3.000"), Decimal("8.00")),
                (default, Decimal("1.000"), Decimal("5.00")),
            ],
        )
        sales_return, _items = _make_sales_return(
            shop,
            order,
            owner,
            [
                (kg, Decimal("1.000"), Decimal("10.00")),
                (pack, Decimal("1.000"), Decimal("8.00")),
                (default, Decimal("1.000"), Decimal("5.00")),
            ],
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        kg_detail = api_client.get(reverse("get_product_detail", args=[kg.id]))
        pack_detail = api_client.get(reverse("get_product_detail", args=[pack.id]))
        default_detail = api_client.get(
            reverse("get_product_detail", args=[default.id])
        )
        return_list = api_client.get(reverse("sales-return-list"))
        return_detail = api_client.get(
            reverse("sales-return-detail", args=[sales_return.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert kg_detail.status_code == status.HTTP_200_OK
        assert pack_detail.status_code == status.HTTP_200_OK
        assert default_detail.status_code == status.HTTP_200_OK
        assert return_list.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK

        list_return = _return_from_list(return_list.data, sales_return.id)
        for product, expected, detail in (
            (kg, "kg", kg_detail.data),
            (pack, "pack", pack_detail.data),
            (default, "piece", default_detail.data),
        ):
            catalog = _row_by_id(listed.data, product.id)
            for payload in (return_detail.data, list_return):
                item = _item_by_product(payload, product.id)
                assert "unit" in item
                assert item["unit"] == expected
                assert item["unit"] == catalog["unit"]
                assert item["unit"] == detail["unit"]
                assert item["product_name"] == product.name

    def test_empty_unit_stays_empty_like_list(self, api_client):
        owner, shop = _make_retailer("oe313_empty_own", "OE313 Empty Shop")
        category = _make_category(shop, "OE313 Empty Cat")
        product = _make_product(shop, category, "OE313 Blank Unit", unit="kg")
        Product.objects.filter(pk=product.id).update(unit="")
        product.refresh_from_db()
        assert product.unit == ""
        order = _make_order(shop, [(product, Decimal("1.000"), Decimal("10.00"))])
        sales_return, _items = _make_sales_return(
            shop,
            order,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        return_detail = api_client.get(
            reverse("sales-return-detail", args=[sales_return.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK
        item = _item_by_product(return_detail.data, product.id)
        catalog = _row_by_id(listed.data, product.id)
        assert item["unit"] == catalog["unit"]
        assert item["unit"] == detail.data["unit"]
        assert item["unit"] == ""
        assert item["unit"] != "piece"

    def test_write_payload_unit_is_ignored(self, api_client):
        owner, shop = _make_retailer("oe313_write_own", "OE313 Write Shop")
        category = _make_category(shop, "OE313 Write Cat")
        product = _make_product(shop, category, "OE313 Write Atta", unit="kg")
        order = _make_order(shop, [(product, Decimal("2.000"), Decimal("10.00"))])
        order_item = order.items.get(product=product)

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("sales-return-list"),
            {
                "order_id": order.id,
                "refund_payment_mode": "cash",
                "reason": "OE-313 write ignore",
                "items": [
                    {
                        "product_id": product.id,
                        "order_item_id": order_item.id,
                        "quantity": 1,
                        "refund_unit_price": "10.00",
                        "unit": "liter",
                    }
                ],
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        item = _item_by_product(created.data, product.id)
        assert item["unit"] == "kg"
        product.refresh_from_db()
        assert product.unit == "kg"

    def test_unauthenticated_denied(self, api_client):
        owner, shop = _make_retailer("oe313_auth_own", "OE313 Auth Shop")
        category = _make_category(shop, "OE313 Auth Cat")
        product = _make_product(shop, category, "OE313 Auth Rice", unit="kg")
        order = _make_order(shop, [(product, Decimal("1.000"), Decimal("10.00"))])
        sales_return, _items = _make_sales_return(
            shop,
            order,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        listed = api_client.get(reverse("sales-return-list"))
        detail = api_client.get(
            reverse("sales-return-detail", args=[sales_return.id])
        )
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert detail.status_code == status.HTTP_401_UNAUTHORIZED

    def test_return_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("oe313_ten_a", "OE313 Tenant A")
        owner_b, shop_b = _make_retailer("oe313_ten_b", "OE313 Tenant B")
        cat_a = _make_category(shop_a, "OE313 A Cat")
        cat_b = _make_category(shop_b, "OE313 B Cat")
        product_a = _make_product(shop_a, cat_a, "OE313 A SKU", unit="liter")
        product_b = _make_product(shop_b, cat_b, "OE313 B SKU", unit="dozen")
        ret_a, _ = _make_sales_return(
            shop_a,
            _make_order(shop_a, [(product_a, Decimal("1.000"), Decimal("10.00"))]),
            owner_a,
            [(product_a, Decimal("1.000"), Decimal("10.00"))],
        )
        ret_b, _ = _make_sales_return(
            shop_b,
            _make_order(shop_b, [(product_b, Decimal("1.000"), Decimal("10.00"))]),
            owner_b,
            [(product_b, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("sales-return-list"))
        foreign = api_client.get(reverse("sales-return-detail", args=[ret_a.id]))
        own = api_client.get(reverse("sales-return-detail", args=[ret_b.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert foreign.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in listed.data["results"]}
        assert ret_a.id not in ids
        assert ret_b.id in ids
        assert _item_by_product(own.data, product_b.id)["unit"] == "dozen"

    def test_pack_identity_echoes_each_sku_unit_no_conversion(self, api_client):
        owner, shop = _make_retailer("oe313_pack_own", "OE313 Pack Shop")
        category = _make_category(shop, "OE313 Pack Cat")
        parent = _make_product(
            shop,
            category,
            "OE313 Case",
            unit="box",
            is_parent_bulk=True,
            price=Decimal("100.00"),
            purchase_price=Decimal("60.00"),
            conversion_factor=Decimal("1.0000"),
        )
        child = _make_product(
            shop,
            category,
            "OE313 Piece",
            unit="piece",
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.1000"),
            price=Decimal("12.00"),
            purchase_price=Decimal("6.00"),
        )
        order = _make_order(
            shop,
            [
                (parent, Decimal("1.000"), Decimal("60.00")),
                (child, Decimal("10.000"), Decimal("6.00")),
            ],
        )
        sales_return, _items = _make_sales_return(
            shop,
            order,
            owner,
            [
                (parent, Decimal("1.000"), Decimal("60.00")),
                (child, Decimal("2.000"), Decimal("6.00")),
            ],
        )

        api_client.force_authenticate(user=owner)
        parent_detail = api_client.get(reverse("get_product_detail", args=[parent.id]))
        child_detail = api_client.get(reverse("get_product_detail", args=[child.id]))
        return_detail = api_client.get(
            reverse("sales-return-detail", args=[sales_return.id])
        )

        assert parent_detail.status_code == status.HTTP_200_OK
        assert child_detail.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK
        parent_item = _item_by_product(return_detail.data, parent.id)
        child_item = _item_by_product(return_detail.data, child.id)
        assert parent_item["unit"] == parent_detail.data["unit"] == "box"
        assert child_item["unit"] == child_detail.data["unit"] == "piece"
        assert parent_item["unit"] != child_item["unit"]
        assert Decimal(str(child.conversion_factor)) == Decimal("0.1000")

    def test_select_related_product_adds_no_unit_query(self):
        _owner, shop = _make_retailer("oe313_n1_own", "OE313 N1 Shop")
        category = _make_category(shop, "OE313 N1 Cat")
        products = [
            _make_product(shop, category, f"OE313 N1 {unit}", unit=unit)
            for unit in ("kg", "pack", "liter")
        ]
        order = _make_order(
            shop,
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )
        sales_return, _items = _make_sales_return(
            shop,
            order,
            _owner,
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )

        loaded = list(
            SalesReturnItem.objects.select_related("product")
            .filter(sales_return=sales_return)
            .order_by("id")
        )
        with CaptureQueriesContext(connection) as captured:
            data = SalesReturnItemSerializer(loaded, many=True).data

        assert [row["unit"] for row in data] == ["kg", "pack", "liter"]
        assert _product_table_reads(captured) == []

    def test_unit_does_not_double_product_fetch(self):
        _owner, shop = _make_retailer("oe313_n1b_own", "OE313 N1B Shop")
        category = _make_category(shop, "OE313 N1B Cat")
        products = [
            _make_product(shop, category, f"OE313 N1B {unit}", unit=unit)
            for unit in ("kg", "pack", "liter")
        ]
        order = _make_order(
            shop,
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )
        sales_return, _items = _make_sales_return(
            shop,
            order,
            _owner,
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )

        cold = list(SalesReturnItem.objects.filter(sales_return=sales_return))
        with CaptureQueriesContext(connection) as captured:
            data = SalesReturnItemSerializer(cold, many=True).data

        assert {row["unit"] for row in data} == {"kg", "pack", "liter"}
        assert {row["product_name"] for row in data} == {
            "OE313 N1B kg",
            "OE313 N1B pack",
            "OE313 N1B liter",
        }
        assert len(_product_table_reads(captured)) == 3

    def test_prefetched_return_items_add_no_product_query(self):
        owner, shop = _make_retailer("oe313_n1c_own", "OE313 N1C Shop")
        category = _make_category(shop, "OE313 N1C Cat")
        product = _make_product(shop, category, "OE313 N1C Sugar", unit="kg")
        order = _make_order(shop, [(product, Decimal("1.000"), Decimal("10.00"))])
        sales_return, _items = _make_sales_return(
            shop,
            order,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        loaded = (
            SalesReturn.objects.select_related("order", "created_by")
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=SalesReturnItem.objects.select_related("product"),
                )
            )
            .get(pk=sales_return.id)
        )

        with CaptureQueriesContext(connection) as captured:
            payload = SalesReturnSerializer(loaded).data

        assert _item_by_product(payload, product.id)["unit"] == "kg"
        assert _product_table_reads(captured) == []
