"""
OE-355 / F follow-on — optional unit on purchase-return line items.

Same value as list/detail Product.unit when product.unit exists.
Empty/null stays empty/null (no invented 'piece' on read).
Auth/tenancy unchanged. READ only. Dummy hosts only.

Sales-return unit is OE-313 (SalesReturnItemSerializer) — this file
covers PurchaseReturnItemSerializer only.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.db.models import Prefetch
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory, PurchaseInvoice, PurchaseItem
from retailers.models import RetailerProfile, Supplier
from retailers.organization import ensure_organization_for_profile
from returns.models import PurchaseReturn, PurchaseReturnItem
from returns.serializers import PurchaseReturnItemSerializer, PurchaseReturnSerializer


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


def _make_supplier(retailer, name):
    return Supplier.objects.create(retailer=retailer, company_name=name, is_active=True)


def _make_invoice(retailer, supplier, invoice_number, items):
    invoice = PurchaseInvoice.objects.create(
        retailer=retailer,
        supplier=supplier,
        invoice_number=invoice_number,
        invoice_date="2026-09-18",
        total_amount=Decimal("10.00"),
        paid_amount=Decimal("0.00"),
        payment_status="UNPAID",
    )
    created = []
    for product, quantity, purchase_price in items:
        created.append(
            PurchaseItem.objects.create(
                invoice=invoice,
                product=product,
                quantity=quantity,
                purchase_price=purchase_price,
                total=quantity * purchase_price,
            )
        )
    return invoice, created


def _make_purchase_return(retailer, supplier, invoice, created_by, items):
    purchase_return = PurchaseReturn.objects.create(
        retailer=retailer,
        supplier=supplier,
        invoice=invoice,
        return_number="RET-DUMMY-READ",
        notes="dummy purchase-return unit echo",
        created_by=created_by,
        total_amount=Decimal("0.00"),
    )
    total = Decimal("0.00")
    created = []
    for product, quantity, purchase_price, purchase_item in items:
        line_total = quantity * purchase_price
        created.append(
            PurchaseReturnItem.objects.create(
                purchase_return=purchase_return,
                product=product,
                purchase_item=purchase_item,
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


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestPurchaseReturnItemUnit:
    def test_item_unit_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("pr_unit_hit_own", "PR Unit Shop")
        category = _make_category(shop, "PR Unit Cat")
        kg = _make_product(shop, category, "PR Atta", unit="kg")
        pack = _make_product(shop, category, "PR Biscuits", unit="pack")
        default = _make_product(shop, category, "PR Piece Default", unit="piece")
        supplier = _make_supplier(shop, "PR Unit Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-UNIT-HIT",
            [
                (kg, Decimal("2.000"), Decimal("10.00")),
                (pack, Decimal("3.000"), Decimal("8.00")),
                (default, Decimal("1.000"), Decimal("5.00")),
            ],
        )
        item_by_product = {row.product_id: row for row in invoice_items}
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [
                (kg, Decimal("1.000"), Decimal("10.00"), item_by_product[kg.id]),
                (pack, Decimal("1.000"), Decimal("8.00"), item_by_product[pack.id]),
                (default, Decimal("1.000"), Decimal("5.00"), item_by_product[default.id]),
            ],
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        kg_detail = api_client.get(reverse("get_product_detail", args=[kg.id]))
        pack_detail = api_client.get(reverse("get_product_detail", args=[pack.id]))
        default_detail = api_client.get(
            reverse("get_product_detail", args=[default.id])
        )
        return_list = api_client.get(reverse("purchase-return-list"))
        return_detail = api_client.get(
            reverse("purchase-return-detail", args=[purchase_return.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert kg_detail.status_code == status.HTTP_200_OK
        assert pack_detail.status_code == status.HTTP_200_OK
        assert default_detail.status_code == status.HTTP_200_OK
        assert return_list.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK

        list_return = _return_from_list(return_list.data, purchase_return.id)
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
        owner, shop = _make_retailer("pr_unit_empty_own", "PR Empty Shop")
        category = _make_category(shop, "PR Empty Cat")
        product = _make_product(shop, category, "PR Blank Unit", unit="kg")
        Product.objects.filter(pk=product.id).update(unit="")
        product.refresh_from_db()
        assert product.unit == ""
        supplier = _make_supplier(shop, "PR Empty Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-UNIT-EMPTY",
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"), invoice_items[0])],
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
        assert item["unit"] == catalog["unit"]
        assert item["unit"] == detail.data["unit"]
        assert item["unit"] == ""
        assert item["unit"] != "piece"

    def test_write_payload_unit_is_ignored(self, api_client):
        owner, shop = _make_retailer("pr_unit_write_own", "PR Write Shop")
        category = _make_category(shop, "PR Write Cat")
        product = _make_product(shop, category, "PR Write Atta", unit="kg")
        supplier = _make_supplier(shop, "PR Write Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-UNIT-WRITE",
            [(product, Decimal("2.000"), Decimal("10.00"))],
        )
        purchase_item = invoice_items[0]

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("purchase-return-list"),
            {
                "supplier_id": supplier.id,
                "invoice_id": invoice.id,
                "notes": "dummy write ignore",
                "items": [
                    {
                        "product_id": product.id,
                        "purchase_item_id": purchase_item.id,
                        "quantity": 1,
                        "purchase_price": "10.00",
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
        owner, shop = _make_retailer("pr_unit_auth_own", "PR Auth Shop")
        category = _make_category(shop, "PR Auth Cat")
        product = _make_product(shop, category, "PR Auth Rice", unit="kg")
        supplier = _make_supplier(shop, "PR Auth Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-UNIT-AUTH",
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"), invoice_items[0])],
        )

        listed = api_client.get(reverse("purchase-return-list"))
        detail = api_client.get(
            reverse("purchase-return-detail", args=[purchase_return.id])
        )
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert detail.status_code == status.HTTP_401_UNAUTHORIZED

    def test_return_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("pr_unit_ten_a", "PR Tenant A")
        owner_b, shop_b = _make_retailer("pr_unit_ten_b", "PR Tenant B")
        cat_a = _make_category(shop_a, "PR A Cat")
        cat_b = _make_category(shop_b, "PR B Cat")
        product_a = _make_product(shop_a, cat_a, "PR A SKU", unit="liter")
        product_b = _make_product(shop_b, cat_b, "PR B SKU", unit="dozen")
        supplier_a = _make_supplier(shop_a, "PR A Vendor")
        supplier_b = _make_supplier(shop_b, "PR B Vendor")
        invoice_a, items_a = _make_invoice(
            shop_a,
            supplier_a,
            "INV-PR-A",
            [(product_a, Decimal("1.000"), Decimal("10.00"))],
        )
        invoice_b, items_b = _make_invoice(
            shop_b,
            supplier_b,
            "INV-PR-B",
            [(product_b, Decimal("1.000"), Decimal("10.00"))],
        )
        ret_a, _ = _make_purchase_return(
            shop_a,
            supplier_a,
            invoice_a,
            owner_a,
            [(product_a, Decimal("1.000"), Decimal("10.00"), items_a[0])],
        )
        ret_b, _ = _make_purchase_return(
            shop_b,
            supplier_b,
            invoice_b,
            owner_b,
            [(product_b, Decimal("1.000"), Decimal("10.00"), items_b[0])],
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
        assert _item_by_product(own.data, product_b.id)["unit"] == "dozen"

    def test_pack_identity_echoes_each_sku_unit_no_conversion(self, api_client):
        owner, shop = _make_retailer("pr_unit_pack_own", "PR Pack Shop")
        category = _make_category(shop, "PR Pack Cat")
        parent = _make_product(
            shop,
            category,
            "PR Case",
            unit="box",
            is_parent_bulk=True,
            price=Decimal("100.00"),
            purchase_price=Decimal("60.00"),
            conversion_factor=Decimal("1.0000"),
        )
        child = _make_product(
            shop,
            category,
            "PR Piece",
            unit="piece",
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.1000"),
            price=Decimal("12.00"),
            purchase_price=Decimal("6.00"),
        )
        supplier = _make_supplier(shop, "PR Pack Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-PACK",
            [
                (parent, Decimal("1.000"), Decimal("60.00")),
                (child, Decimal("10.000"), Decimal("6.00")),
            ],
        )
        item_by_product = {row.product_id: row for row in invoice_items}
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [
                (parent, Decimal("1.000"), Decimal("60.00"), item_by_product[parent.id]),
                (child, Decimal("2.000"), Decimal("6.00"), item_by_product[child.id]),
            ],
        )

        api_client.force_authenticate(user=owner)
        parent_detail = api_client.get(reverse("get_product_detail", args=[parent.id]))
        child_detail = api_client.get(reverse("get_product_detail", args=[child.id]))
        return_detail = api_client.get(
            reverse("purchase-return-detail", args=[purchase_return.id])
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
        owner, shop = _make_retailer("pr_unit_n1_own", "PR N1 Shop")
        category = _make_category(shop, "PR N1 Cat")
        products = [
            _make_product(shop, category, f"PR N1 {unit}", unit=unit)
            for unit in ("kg", "pack", "liter")
        ]
        supplier = _make_supplier(shop, "PR N1 Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-N1",
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )
        item_by_product = {row.product_id: row for row in invoice_items}
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [
                (product, Decimal("1.000"), Decimal("10.00"), item_by_product[product.id])
                for product in products
            ],
        )

        loaded = list(
            PurchaseReturnItem.objects.select_related("product")
            .filter(purchase_return=purchase_return)
            .order_by("id")
        )
        with CaptureQueriesContext(connection) as captured:
            data = PurchaseReturnItemSerializer(loaded, many=True).data

        assert [row["unit"] for row in data] == ["kg", "pack", "liter"]
        assert _product_table_reads(captured) == []

    def test_unit_does_not_double_product_fetch(self):
        owner, shop = _make_retailer("pr_unit_n1b_own", "PR N1B Shop")
        category = _make_category(shop, "PR N1B Cat")
        products = [
            _make_product(shop, category, f"PR N1B {unit}", unit=unit)
            for unit in ("kg", "pack", "liter")
        ]
        supplier = _make_supplier(shop, "PR N1B Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-N1B",
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )
        item_by_product = {row.product_id: row for row in invoice_items}
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [
                (product, Decimal("1.000"), Decimal("10.00"), item_by_product[product.id])
                for product in products
            ],
        )

        cold = list(PurchaseReturnItem.objects.filter(purchase_return=purchase_return))
        with CaptureQueriesContext(connection) as captured:
            data = PurchaseReturnItemSerializer(cold, many=True).data

        assert {row["unit"] for row in data} == {"kg", "pack", "liter"}
        assert {row["product_name"] for row in data} == {
            "PR N1B kg",
            "PR N1B pack",
            "PR N1B liter",
        }
        assert len(_product_table_reads(captured)) == 3

    def test_prefetched_return_items_add_no_product_query(self):
        owner, shop = _make_retailer("pr_unit_n1c_own", "PR N1C Shop")
        category = _make_category(shop, "PR N1C Cat")
        product = _make_product(shop, category, "PR N1C Sugar", unit="kg")
        supplier = _make_supplier(shop, "PR N1C Vendor")
        invoice, invoice_items = _make_invoice(
            shop,
            supplier,
            "INV-PR-N1C",
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"), invoice_items[0])],
        )
        loaded = (
            PurchaseReturn.objects.select_related("supplier", "invoice", "created_by")
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=PurchaseReturnItem.objects.select_related("product"),
                )
            )
            .get(pk=purchase_return.id)
        )

        with CaptureQueriesContext(connection) as captured:
            payload = PurchaseReturnSerializer(loaded).data

        assert _item_by_product(payload, product.id)["unit"] == "kg"
        assert _product_table_reads(captured) == []
