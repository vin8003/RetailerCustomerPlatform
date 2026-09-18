"""
Optional supplier_code on purchase-invoice list.

Echo PurchaseInvoice.supplier_code or Supplier.supplier_code only when that
attribute exists. Missing field or null stays null (no invented code).
List only — detail / write serializers stay unchanged.
Does not touch ProductSearchSerializer Meta, cart, or returns.
Dummy / local only. Never *.ordereasy.win.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from cart.serializers import CartItemSerializer
from products.models import Product, ProductCategory, PurchaseInvoice
from products.serializers import (
    ProductSearchSerializer,
    PurchaseInvoiceListSerializer,
    PurchaseInvoiceSerializer,
    purchase_invoice_supplier_code,
)
from retailers.models import RetailerProfile, Supplier
from retailers.organization import ensure_organization_for_profile
from returns.serializers import (
    PurchaseReturnItemSerializer,
    SalesReturnItemSerializer,
)


# Same budget as products/tests/test_purchase_invoice_supplier_gate_oe100.py
PI_LIST_FIXED_QUERIES = 4
PI_LIST_PER_INVOICE_QUERIES = 4


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


def _make_supplier(retailer, company_name):
    return Supplier.objects.create(
        retailer=retailer,
        company_name=company_name,
        contact_person="PI-SC",
    )


def _make_invoice(retailer, supplier, invoice_number):
    return PurchaseInvoice.objects.create(
        retailer=retailer,
        supplier=supplier,
        invoice_number=invoice_number,
        invoice_date="2026-09-18",
        total_amount=Decimal("10.00"),
        paid_amount=Decimal("0.00"),
    )


def _rows(payload):
    return payload if isinstance(payload, list) else payload.get("results") or []


def _list_row(payload, invoice_id):
    for row in _rows(payload):
        if row["id"] == invoice_id:
            return row
    raise AssertionError(f"invoice {invoice_id} missing from list payload")


def _supplier_table_reads(captured):
    return [
        q["sql"]
        for q in captured.captured_queries
        if 'FROM "supplier"' in q["sql"]
    ]


@pytest.mark.django_db
class TestPurchaseInvoiceListSupplierCode:
    def test_helper_none_without_attribute(self):
        owner, shop = _make_retailer("pisc_help_own", "PISC Help Shop")
        supplier = _make_supplier(shop, "PISC Help Supplier")
        invoice = _make_invoice(shop, supplier, "INV-PISC-HELP")
        assert purchase_invoice_supplier_code(None) is None
        assert not hasattr(invoice, "supplier_code")
        assert not hasattr(supplier, "supplier_code")
        assert purchase_invoice_supplier_code(invoice) is None

    def test_list_missing_field_is_null(self, api_client):
        owner, shop = _make_retailer("pisc_miss_own", "PISC Miss Shop")
        supplier = _make_supplier(shop, "PISC Miss Supplier")
        invoice = _make_invoice(shop, supplier, "INV-PISC-MISS")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("erp-purchase-invoice-list"))
        detail = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[invoice.id])
        )

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert detail.status_code == status.HTTP_200_OK, detail.data
        row = _list_row(listed.data, invoice.id)
        assert "supplier_code" in row
        assert row["supplier_code"] is None
        assert row["supplier_name"] == "PISC Miss Supplier"
        assert "supplier_code" not in detail.data

    def test_serializer_echoes_invoice_attribute(self):
        owner, shop = _make_retailer("pisc_inv_own", "PISC Inv Shop")
        supplier = _make_supplier(shop, "PISC Inv Supplier")
        invoice = _make_invoice(shop, supplier, "INV-PISC-INV")
        invoice.supplier_code = "VEND-42"

        data = PurchaseInvoiceListSerializer(invoice).data
        assert data["supplier_code"] == "VEND-42"
        assert data["supplier_name"] == "PISC Inv Supplier"
        assert purchase_invoice_supplier_code(invoice) == "VEND-42"

    def test_serializer_echoes_supplier_attribute(self):
        owner, shop = _make_retailer("pisc_sup_own", "PISC Sup Shop")
        supplier = _make_supplier(shop, "PISC Sup Supplier")
        invoice = _make_invoice(shop, supplier, "INV-PISC-SUP")
        supplier.supplier_code = "SUP-99"

        data = PurchaseInvoiceListSerializer(invoice).data
        assert data["supplier_code"] == "SUP-99"
        assert purchase_invoice_supplier_code(invoice) == "SUP-99"

    def test_serializer_null_passthrough(self):
        owner, shop = _make_retailer("pisc_null_own", "PISC Null Shop")
        supplier = _make_supplier(shop, "PISC Null Supplier")
        invoice = _make_invoice(shop, supplier, "INV-PISC-NULL")
        invoice.supplier_code = None

        assert PurchaseInvoiceListSerializer(invoice).data["supplier_code"] is None

    def test_serializer_empty_passthrough(self):
        owner, shop = _make_retailer("pisc_empty_own", "PISC Empty Shop")
        supplier = _make_supplier(shop, "PISC Empty Supplier")
        invoice = _make_invoice(shop, supplier, "INV-PISC-EMPTY")
        invoice.supplier_code = ""

        assert PurchaseInvoiceListSerializer(invoice).data["supplier_code"] == ""

    def test_write_payload_supplier_code_is_ignored(self, api_client):
        owner, shop = _make_retailer("pisc_write_own", "PISC Write Shop")
        supplier = _make_supplier(shop, "PISC Write Supplier")
        category = ProductCategory.objects.create(name="PISC Write Cat", retailer=shop)
        product = Product.objects.create(
            retailer=shop,
            name="PISC Write Rice",
            category=category,
            price=Decimal("12.00"),
            quantity=Decimal("50"),
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="kg",
        )

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("erp-purchase-invoice-list"),
            {
                "supplier": supplier.id,
                "invoice_number": "INV-PISC-WRITE",
                "invoice_date": "2026-09-18",
                "total_amount": "20.00",
                "paid_amount": "0.00",
                "payment_status": "UNPAID",
                "supplier_code": "SHOULD-IGNORE",
                "items": [
                    {
                        "product": product.id,
                        "quantity": 2,
                        "purchase_price": "10.00",
                        "total": "20.00",
                    }
                ],
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        assert "supplier_code" not in created.data
        invoice = PurchaseInvoice.objects.get(invoice_number="INV-PISC-WRITE")
        assert not hasattr(invoice, "supplier_code")
        invoice.refresh_from_db()
        assert not hasattr(invoice, "supplier_code")

    def test_unauthenticated_denied(self, api_client):
        owner, shop = _make_retailer("pisc_auth_own", "PISC Auth Shop")
        supplier = _make_supplier(shop, "PISC Auth Supplier")
        invoice = _make_invoice(shop, supplier, "INV-PISC-AUTH")

        listed = api_client.get(reverse("erp-purchase-invoice-list"))
        detail = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[invoice.id])
        )
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert detail.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("pisc_ten_a", "PISC Tenant A")
        owner_b, shop_b = _make_retailer("pisc_ten_b", "PISC Tenant B")
        inv_a = _make_invoice(
            shop_a, _make_supplier(shop_a, "PISC A Supplier"), "INV-PISC-A"
        )
        inv_b = _make_invoice(
            shop_b, _make_supplier(shop_b, "PISC B Supplier"), "INV-PISC-B"
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("erp-purchase-invoice-list"))
        foreign = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[inv_a.id])
        )
        own = api_client.get(
            reverse("erp-purchase-invoice-detail", args=[inv_b.id])
        )

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert foreign.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK, own.data
        ids = {row["id"] for row in _rows(listed.data)}
        assert inv_a.id not in ids
        assert inv_b.id in ids
        assert _list_row(listed.data, inv_b.id)["supplier_code"] is None
        assert "supplier_code" not in own.data

    def test_list_query_budget_unchanged(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("pisc_q_own", "PISC Query Shop")
        _make_invoice(shop, _make_supplier(shop, "Vendor 0"), "INV-PISC-Q0")

        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(
            PI_LIST_FIXED_QUERIES + PI_LIST_PER_INVOICE_QUERIES
        ):
            listed = api_client.get(reverse("erp-purchase-invoice-list"))

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert [_list_row(listed.data, row["id"])["supplier_code"] for row in _rows(listed.data)] == [None]
        assert [row["supplier_name"] for row in _rows(listed.data)] == ["Vendor 0"]

    def test_list_adds_no_standalone_supplier_query(self, api_client):
        owner, shop = _make_retailer("pisc_n1_own", "PISC N1 Shop")
        for i in range(3):
            _make_invoice(
                shop,
                _make_supplier(shop, f"Vendor {i}"),
                f"INV-PISC-N1-{i}",
            )

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as captured:
            listed = api_client.get(reverse("erp-purchase-invoice-list"))

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert len(_rows(listed.data)) == 3
        assert all(row["supplier_code"] is None for row in _rows(listed.data))
        assert _supplier_table_reads(captured) == []

    def test_hot_paths_stay_without_supplier_code(self):
        assert "supplier_code" not in ProductSearchSerializer.Meta.fields
        assert "supplier_code" not in CartItemSerializer.Meta.fields
        assert "supplier_code" not in SalesReturnItemSerializer.Meta.fields
        assert "supplier_code" not in PurchaseReturnItemSerializer.Meta.fields
        assert "supplier_code" not in PurchaseInvoiceSerializer.Meta.fields
        assert "supplier_code" in PurchaseInvoiceListSerializer.Meta.fields
