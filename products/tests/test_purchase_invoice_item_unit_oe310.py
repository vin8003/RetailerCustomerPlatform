"""
OE-310 / F follow-on — top-level unit on purchase invoice line items.

Same value as list/detail Product.unit. Empty/null stays empty/null
(no invented 'piece' on read). Auth/tenancy unchanged. READ only.
Does not touch ProductSearchSerializer Meta or POS views.
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
from products.serializers import PurchaseItemSerializer
from retailers.models import RetailerProfile, Supplier
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


def _item_by_product(payload, product_id):
    items = payload.get("items") or []
    for row in items:
        if row["product"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from invoice items")


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _product_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "product"' in q["sql"]
    ]


@pytest.mark.django_db
class TestPurchaseInvoiceItemUnit:
    def test_item_unit_matches_list_and_detail(self, api_client):
        owner, shop = _make_retailer("oe310_hit_own", "OE310 Unit Shop")
        category = _make_category(shop, "OE310 Unit Cat")
        kg = _make_product(shop, category, "OE310 Atta", unit="kg")
        pack = _make_product(shop, category, "OE310 Biscuits", unit="pack")
        default = _make_product(shop, category, "OE310 Piece Default", unit="piece")
        supplier = _make_supplier(shop, "OE310 Unit Vendor")
        invoice, _items = _make_invoice(
            shop,
            supplier,
            "INV-OE310-HIT",
            [
                (kg, Decimal("2.000"), Decimal("10.00")),
                (pack, Decimal("3.000"), Decimal("8.00")),
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
        invoice_list = api_client.get(reverse("erp-purchase-invoice-list"))
        invoice_detail = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[invoice.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert kg_detail.status_code == status.HTTP_200_OK
        assert pack_detail.status_code == status.HTTP_200_OK
        assert default_detail.status_code == status.HTTP_200_OK
        assert invoice_list.status_code == status.HTTP_200_OK
        assert invoice_detail.status_code == status.HTTP_200_OK

        list_invoice = next(
            row for row in invoice_list.data["results"] if row["id"] == invoice.id
        )
        for product, expected, detail in (
            (kg, "kg", kg_detail.data),
            (pack, "pack", pack_detail.data),
            (default, "piece", default_detail.data),
        ):
            catalog = _row_by_id(listed.data, product.id)
            for payload in (invoice_detail.data, list_invoice):
                item = _item_by_product(payload, product.id)
                assert "unit" in item
                assert item["unit"] == expected
                assert item["unit"] == catalog["unit"]
                assert item["unit"] == detail["unit"]

    def test_empty_unit_stays_empty_like_list(self, api_client):
        owner, shop = _make_retailer("oe310_empty_own", "OE310 Empty Shop")
        category = _make_category(shop, "OE310 Empty Cat")
        product = _make_product(shop, category, "OE310 Blank Unit", unit="kg")
        Product.objects.filter(pk=product.id).update(unit="")
        product.refresh_from_db()
        assert product.unit == ""
        supplier = _make_supplier(shop, "OE310 Empty Vendor")
        invoice, _items = _make_invoice(
            shop,
            supplier,
            "INV-OE310-EMPTY",
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        invoice_detail = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[invoice.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        assert invoice_detail.status_code == status.HTTP_200_OK
        item = _item_by_product(invoice_detail.data, product.id)
        catalog = _row_by_id(listed.data, product.id)
        assert item["unit"] == catalog["unit"]
        assert item["unit"] == detail.data["unit"]
        assert item["unit"] == ""
        assert item["unit"] != "piece"

    def test_null_product_unit_is_null(self):
        _owner, shop = _make_retailer("oe310_null_own", "OE310 Null Shop")
        category = _make_category(shop, "OE310 Null Cat")
        product = _make_product(shop, category, "OE310 Then Deleted", unit="liter")
        supplier = _make_supplier(shop, "OE310 Null Vendor")
        _invoice, items = _make_invoice(
            shop,
            supplier,
            "INV-OE310-NULL",
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        line = items[0]
        line.product = None
        line.save(update_fields=["product"])

        data = PurchaseItemSerializer(line).data
        assert data["unit"] is None
        assert data["product"] is None

    def test_write_payload_unit_is_ignored(self, api_client):
        owner, shop = _make_retailer("oe310_write_own", "OE310 Write Shop")
        category = _make_category(shop, "OE310 Write Cat")
        product = _make_product(shop, category, "OE310 Write Atta", unit="kg")
        supplier = _make_supplier(shop, "OE310 Write Vendor")

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("erp-purchase-invoice-list"),
            {
                "supplier": supplier.id,
                "invoice_number": "INV-OE310-WRITE",
                "invoice_date": "2026-09-18",
                "total_amount": "10.00",
                "paid_amount": "0.00",
                "payment_status": "UNPAID",
                "items": [
                    {
                        "product": product.id,
                        "quantity": 1,
                        "purchase_price": "10.00",
                        "total": "10.00",
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
        owner, shop = _make_retailer("oe310_auth_own", "OE310 Auth Shop")
        category = _make_category(shop, "OE310 Auth Cat")
        product = _make_product(shop, category, "OE310 Auth Rice", unit="kg")
        supplier = _make_supplier(shop, "OE310 Auth Vendor")
        invoice, _items = _make_invoice(
            shop,
            supplier,
            "INV-OE310-AUTH",
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        listed = api_client.get(reverse("erp-purchase-invoice-list"))
        detail = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[invoice.id])
        )
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert detail.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invoice_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe310_ten_a", "OE310 Tenant A")
        owner_b, shop_b = _make_retailer("oe310_ten_b", "OE310 Tenant B")
        cat_a = _make_category(shop_a, "OE310 A Cat")
        cat_b = _make_category(shop_b, "OE310 B Cat")
        product_a = _make_product(shop_a, cat_a, "OE310 A SKU", unit="liter")
        product_b = _make_product(shop_b, cat_b, "OE310 B SKU", unit="dozen")
        inv_a, _ = _make_invoice(
            shop_a,
            _make_supplier(shop_a, "OE310 A Vendor"),
            "INV-OE310-A",
            [(product_a, Decimal("1.000"), Decimal("10.00"))],
        )
        inv_b, _ = _make_invoice(
            shop_b,
            _make_supplier(shop_b, "OE310 B Vendor"),
            "INV-OE310-B",
            [(product_b, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("erp-purchase-invoice-list"))
        foreign = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[inv_a.id])
        )
        own = api_client.get(reverse("erp-purchase-invoice-detail", args=[inv_b.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert foreign.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in listed.data["results"]}
        assert inv_a.id not in ids
        assert inv_b.id in ids
        assert _item_by_product(own.data, product_b.id)["unit"] == "dozen"

    def test_pack_identity_echoes_each_sku_unit_no_conversion(self, api_client):
        owner, shop = _make_retailer("oe310_pack_own", "OE310 Pack Shop")
        category = _make_category(shop, "OE310 Pack Cat")
        parent = _make_product(
            shop,
            category,
            "OE310 Case",
            unit="box",
            is_parent_bulk=True,
            price=Decimal("100.00"),
            purchase_price=Decimal("60.00"),
            conversion_factor=Decimal("1.0000"),
        )
        child = _make_product(
            shop,
            category,
            "OE310 Piece",
            unit="piece",
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.1000"),
            price=Decimal("12.00"),
            purchase_price=Decimal("6.00"),
        )
        invoice, _items = _make_invoice(
            shop,
            _make_supplier(shop, "OE310 Pack Vendor"),
            "INV-OE310-PACK",
            [
                (parent, Decimal("1.000"), Decimal("60.00")),
                (child, Decimal("10.000"), Decimal("6.00")),
            ],
        )

        api_client.force_authenticate(user=owner)
        parent_detail = api_client.get(reverse("get_product_detail", args=[parent.id]))
        child_detail = api_client.get(reverse("get_product_detail", args=[child.id]))
        invoice_detail = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[invoice.id])
        )

        assert parent_detail.status_code == status.HTTP_200_OK
        assert child_detail.status_code == status.HTTP_200_OK
        assert invoice_detail.status_code == status.HTTP_200_OK
        parent_item = _item_by_product(invoice_detail.data, parent.id)
        child_item = _item_by_product(invoice_detail.data, child.id)
        assert parent_item["unit"] == parent_detail.data["unit"] == "box"
        assert child_item["unit"] == child_detail.data["unit"] == "piece"
        assert parent_item["unit"] != child_item["unit"]
        assert Decimal(str(child.conversion_factor)) == Decimal("0.1000")

    def test_select_related_product_adds_no_unit_query(self):
        _owner, shop = _make_retailer("oe310_n1_own", "OE310 N1 Shop")
        category = _make_category(shop, "OE310 N1 Cat")
        products = [
            _make_product(shop, category, f"OE310 N1 {unit}", unit=unit)
            for unit in ("kg", "pack", "liter")
        ]
        invoice, _items = _make_invoice(
            shop,
            _make_supplier(shop, "OE310 N1 Vendor"),
            "INV-OE310-N1",
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )

        loaded = list(
            PurchaseItem.objects.select_related("product")
            .filter(invoice=invoice)
            .order_by("id")
        )
        with CaptureQueriesContext(connection) as captured:
            data = PurchaseItemSerializer(loaded, many=True).data

        assert [row["unit"] for row in data] == ["kg", "pack", "liter"]
        assert _product_table_reads(captured) == []

    def test_unit_does_not_double_product_fetch(self):
        _owner, shop = _make_retailer("oe310_n1b_own", "OE310 N1B Shop")
        category = _make_category(shop, "OE310 N1B Cat")
        products = [
            _make_product(shop, category, f"OE310 N1B {unit}", unit=unit)
            for unit in ("kg", "pack", "liter")
        ]
        invoice, _items = _make_invoice(
            shop,
            _make_supplier(shop, "OE310 N1B Vendor"),
            "INV-OE310-N1B",
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )

        cold = list(PurchaseItem.objects.filter(invoice=invoice))
        with CaptureQueriesContext(connection) as captured:
            data = PurchaseItemSerializer(cold, many=True).data

        assert {row["unit"] for row in data} == {"kg", "pack", "liter"}
        assert {row["product_name"] for row in data} == {
            "OE310 N1B kg",
            "OE310 N1B pack",
            "OE310 N1B liter",
        }
        assert len(_product_table_reads(captured)) == 3

    def test_prefetched_invoice_items_add_no_product_query(self):
        _owner, shop = _make_retailer("oe310_n1c_own", "OE310 N1C Shop")
        category = _make_category(shop, "OE310 N1C Cat")
        product = _make_product(shop, category, "OE310 N1C Sugar", unit="kg")
        invoice, _items = _make_invoice(
            shop,
            _make_supplier(shop, "OE310 N1C Vendor"),
            "INV-OE310-N1C",
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        loaded = (
            PurchaseInvoice.objects.select_related("supplier")
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=PurchaseItem.objects.select_related("product"),
                )
            )
            .get(pk=invoice.id)
        )

        from products.serializers import PurchaseInvoiceSerializer

        with CaptureQueriesContext(connection) as captured:
            payload = PurchaseInvoiceSerializer(loaded).data

        assert _item_by_product(payload, product.id)["unit"] == "kg"
        assert _product_table_reads(captured) == []
