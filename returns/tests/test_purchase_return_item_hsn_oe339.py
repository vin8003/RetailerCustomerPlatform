"""
OE-339 / F follow-on — optional hsn_code on purchase-return line items.

Echo Product.hsn_code only when the attribute exists. Missing field or
null stays null (no invented HSN). Auth/tenancy unchanged. READ only.
Does not touch ProductSearchSerializer Meta, POS views, or
SalesReturnItemSerializer (OE-313).
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
from products.models import Product, ProductCategory, PurchaseInvoice, PurchaseItem
from products.serializers import ProductSearchSerializer
from retailers.models import RetailerProfile, Supplier
from retailers.organization import ensure_organization_for_profile
from returns.models import PurchaseReturn, PurchaseReturnItem
from returns.serializers import (
    PurchaseReturnItemSerializer,
    PurchaseReturnSerializer,
    SalesReturnItemSerializer,
    product_hsn_code,
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


def _make_product(retailer, category, name, **kwargs):
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
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _make_supplier(retailer, company_name):
    return Supplier.objects.create(
        retailer=retailer,
        company_name=company_name,
        contact_person="OE-339",
        phone_number="9876543210",
    )


def _make_invoice(retailer, supplier, items):
    invoice = PurchaseInvoice.objects.create(
        retailer=retailer,
        supplier=supplier,
        invoice_number=f"INV-{supplier.id}",
        invoice_date="2026-09-18",
        total_amount=Decimal("100.00"),
        payment_status="UNPAID",
    )
    for product, quantity, purchase_price in items:
        PurchaseItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=quantity,
            purchase_price=purchase_price,
            total=quantity * purchase_price,
        )
    return invoice


def _make_purchase_return(retailer, supplier, invoice, created_by, items):
    purchase_return = PurchaseReturn.objects.create(
        retailer=retailer,
        supplier=supplier,
        invoice=invoice,
        notes="OE-339 read echo",
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
class TestProductHsnCodeHelper:
    def test_missing_attribute_is_null(self):
        assert not hasattr(Product, "hsn_code")
        assert product_hsn_code(SimpleNamespace(name="no-hsn")) is None

    def test_none_product_is_null(self):
        assert product_hsn_code(None) is None

    def test_present_value_is_echoed(self):
        assert product_hsn_code(SimpleNamespace(hsn_code="1006")) == "1006"

    def test_null_and_empty_passthrough(self):
        assert product_hsn_code(SimpleNamespace(hsn_code=None)) is None
        assert product_hsn_code(SimpleNamespace(hsn_code="")) == ""


@pytest.mark.django_db
class TestPurchaseReturnItemHsn:
    def test_item_hsn_null_when_product_has_no_field(self, api_client):
        owner, shop = _make_retailer("oe339_miss_own", "OE339 Missing Shop")
        category = _make_category(shop, "OE339 Missing Cat")
        product = _make_product(shop, category, "OE339 Rice")
        assert not hasattr(product, "hsn_code")
        supplier = _make_supplier(shop, "OE339 Missing Supplier")
        invoice = _make_invoice(
            shop, supplier, [(product, Decimal("2.000"), Decimal("10.00"))]
        )
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner)
        return_list = api_client.get(reverse("purchase-return-list"))
        return_detail = api_client.get(
            reverse("purchase-return-detail", args=[purchase_return.id])
        )

        assert return_list.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK
        list_return = _return_from_list(return_list.data, purchase_return.id)
        for payload in (return_detail.data, list_return):
            item = _item_by_product(payload, product.id)
            assert "hsn_code" in item
            assert item["hsn_code"] is None
            assert item["product_name"] == product.name

    def test_serializer_echoes_hsn_when_attribute_exists(self):
        owner, shop = _make_retailer("oe339_echo_own", "OE339 Echo Shop")
        category = _make_category(shop, "OE339 Echo Cat")
        product = _make_product(shop, category, "OE339 Atta")
        supplier = _make_supplier(shop, "OE339 Echo Supplier")
        invoice = _make_invoice(
            shop, supplier, [(product, Decimal("1.000"), Decimal("10.00"))]
        )
        _purchase_return, items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        line = items[0]
        line.product.hsn_code = "1006"

        data = PurchaseReturnItemSerializer(line).data
        assert data["hsn_code"] == "1006"
        assert data["product_name"] == "OE339 Atta"

    def test_serializer_null_passthrough_when_attribute_is_none(self):
        owner, shop = _make_retailer("oe339_null_own", "OE339 Null Shop")
        category = _make_category(shop, "OE339 Null Cat")
        product = _make_product(shop, category, "OE339 Sugar")
        supplier = _make_supplier(shop, "OE339 Null Supplier")
        invoice = _make_invoice(
            shop, supplier, [(product, Decimal("1.000"), Decimal("10.00"))]
        )
        _purchase_return, items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        line = items[0]
        line.product.hsn_code = None

        assert PurchaseReturnItemSerializer(line).data["hsn_code"] is None

    def test_serializer_empty_passthrough(self):
        owner, shop = _make_retailer("oe339_empty_own", "OE339 Empty Shop")
        category = _make_category(shop, "OE339 Empty Cat")
        product = _make_product(shop, category, "OE339 Salt")
        supplier = _make_supplier(shop, "OE339 Empty Supplier")
        invoice = _make_invoice(
            shop, supplier, [(product, Decimal("1.000"), Decimal("10.00"))]
        )
        _purchase_return, items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )
        line = items[0]
        line.product.hsn_code = ""

        assert PurchaseReturnItemSerializer(line).data["hsn_code"] == ""

    def test_write_payload_hsn_code_is_ignored(self, api_client):
        owner, shop = _make_retailer("oe339_write_own", "OE339 Write Shop")
        category = _make_category(shop, "OE339 Write Cat")
        product = _make_product(shop, category, "OE339 Write Atta")
        supplier = _make_supplier(shop, "OE339 Write Supplier")
        invoice = _make_invoice(
            shop, supplier, [(product, Decimal("2.000"), Decimal("10.00"))]
        )
        purchase_item = invoice.items.get(product=product)

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("purchase-return-list"),
            {
                "supplier_id": supplier.id,
                "invoice_id": invoice.id,
                "notes": "OE-339 write ignore",
                "items": [
                    {
                        "product_id": product.id,
                        "purchase_item_id": purchase_item.id,
                        "quantity": 1,
                        "purchase_price": "10.00",
                        "hsn_code": "9999",
                    }
                ],
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        item = _item_by_product(created.data, product.id)
        assert item["hsn_code"] is None
        product.refresh_from_db()
        assert not hasattr(product, "hsn_code")

    def test_unauthenticated_denied(self, api_client):
        owner, shop = _make_retailer("oe339_auth_own", "OE339 Auth Shop")
        category = _make_category(shop, "OE339 Auth Cat")
        product = _make_product(shop, category, "OE339 Auth Rice")
        supplier = _make_supplier(shop, "OE339 Auth Supplier")
        invoice = _make_invoice(
            shop, supplier, [(product, Decimal("1.000"), Decimal("10.00"))]
        )
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
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
        owner_a, shop_a = _make_retailer("oe339_ten_a", "OE339 Tenant A")
        owner_b, shop_b = _make_retailer("oe339_ten_b", "OE339 Tenant B")
        cat_a = _make_category(shop_a, "OE339 A Cat")
        cat_b = _make_category(shop_b, "OE339 B Cat")
        product_a = _make_product(shop_a, cat_a, "OE339 A SKU")
        product_b = _make_product(shop_b, cat_b, "OE339 B SKU")
        supplier_a = _make_supplier(shop_a, "OE339 A Supplier")
        supplier_b = _make_supplier(shop_b, "OE339 B Supplier")
        ret_a, _ = _make_purchase_return(
            shop_a,
            supplier_a,
            _make_invoice(
                shop_a, supplier_a, [(product_a, Decimal("1.000"), Decimal("10.00"))]
            ),
            owner_a,
            [(product_a, Decimal("1.000"), Decimal("10.00"))],
        )
        ret_b, _ = _make_purchase_return(
            shop_b,
            supplier_b,
            _make_invoice(
                shop_b, supplier_b, [(product_b, Decimal("1.000"), Decimal("10.00"))]
            ),
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
        assert _item_by_product(own.data, product_b.id)["hsn_code"] is None

    def test_select_related_product_adds_no_hsn_query(self):
        owner, shop = _make_retailer("oe339_n1_own", "OE339 N1 Shop")
        category = _make_category(shop, "OE339 N1 Cat")
        products = [
            _make_product(shop, category, f"OE339 N1 {idx}")
            for idx in range(3)
        ]
        supplier = _make_supplier(shop, "OE339 N1 Supplier")
        invoice = _make_invoice(
            shop,
            supplier,
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00")) for product in products],
        )

        loaded = list(
            PurchaseReturnItem.objects.select_related("product")
            .filter(purchase_return=purchase_return)
            .order_by("id")
        )
        for line, code in zip(loaded, ("1006", "1905", None)):
            line.product.hsn_code = code

        with CaptureQueriesContext(connection) as captured:
            data = PurchaseReturnItemSerializer(loaded, many=True).data

        assert [row["hsn_code"] for row in data] == ["1006", "1905", None]
        assert _product_table_reads(captured) == []

    def test_prefetched_return_items_add_no_product_query(self):
        owner, shop = _make_retailer("oe339_n1c_own", "OE339 N1C Shop")
        category = _make_category(shop, "OE339 N1C Cat")
        product = _make_product(shop, category, "OE339 N1C Sugar")
        supplier = _make_supplier(shop, "OE339 N1C Supplier")
        invoice = _make_invoice(
            shop, supplier, [(product, Decimal("1.000"), Decimal("10.00"))]
        )
        purchase_return, _items = _make_purchase_return(
            shop,
            supplier,
            invoice,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
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
        loaded.items.all()[0].product.hsn_code = "1701"

        with CaptureQueriesContext(connection) as captured:
            payload = PurchaseReturnSerializer(loaded).data

        assert _item_by_product(payload, product.id)["hsn_code"] == "1701"
        assert _product_table_reads(captured) == []

    def test_sales_return_item_serializer_stays_without_hsn(self):
        assert "hsn_code" not in SalesReturnItemSerializer.Meta.fields

    def test_product_search_serializer_meta_stays_without_hsn(self):
        assert "hsn_code" not in ProductSearchSerializer.Meta.fields
