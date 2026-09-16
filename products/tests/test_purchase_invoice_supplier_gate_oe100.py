"""
OE-100 / F-0041: inactive supplier cannot be selected on new purchase invoices.

No PurchaseOrder model exists yet (OE-102). This is the current inward path.
OE-102 PO create should call assert_supplier_selectable_for_new_purchase.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError

from products.models import PurchaseInvoice
from retailers.models import Supplier
from retailers.suppliers import (
    INACTIVE_SUPPLIER_MESSAGE,
    assert_supplier_selectable_for_new_purchase,
)


def _invoice_payload(supplier, product, invoice_number="INV-OE100"):
    return {
        "supplier": supplier.id,
        "invoice_number": invoice_number,
        "invoice_date": "2026-09-15",
        "total_amount": "100.00",
        "paid_amount": "0.00",
        "payment_status": "UNPAID",
        "items": [
            {
                "product": product.id,
                "quantity": 10,
                "purchase_price": "10.00",
                "total": "100.00",
            }
        ],
    }


@pytest.mark.django_db
class TestInactiveSupplierPurchaseInvoiceGate:
    @pytest.fixture
    def active_supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer, company_name="Active Vendor", is_active=True
        )

    @pytest.fixture
    def inactive_supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer, company_name="Inactive Vendor", is_active=False
        )

    def test_helper_rejects_inactive(self, inactive_supplier):
        with pytest.raises(ValidationError) as exc:
            assert_supplier_selectable_for_new_purchase(inactive_supplier)
        assert INACTIVE_SUPPLIER_MESSAGE in str(exc.value.detail)

    def test_helper_allows_active(self, active_supplier):
        assert_supplier_selectable_for_new_purchase(active_supplier)

    def test_create_rejects_inactive_supplier(
        self, api_client, retailer_user, retailer, inactive_supplier, product
    ):
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(inactive_supplier, product, "INV-INACTIVE"),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert INACTIVE_SUPPLIER_MESSAGE in str(resp.data.get("supplier"))
        assert not PurchaseInvoice.objects.filter(invoice_number="INV-INACTIVE").exists()
        product.refresh_from_db()
        assert product.quantity == Decimal("50")

    def test_create_allows_active_supplier(
        self, api_client, retailer_user, retailer, active_supplier, product
    ):
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(active_supplier, product, "INV-ACTIVE"),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["supplier"] == active_supplier.id

    def test_existing_invoice_keeps_inactive_supplier_on_scalar_patch(
        self, api_client, retailer_user, retailer, active_supplier, product
    ):
        api_client.force_authenticate(user=retailer_user)
        created = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(active_supplier, product, "INV-THEN-INACTIVE"),
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        invoice_id = created.data["id"]
        active_supplier.is_active = False
        active_supplier.save(update_fields=["is_active"])

        patched = api_client.patch(
            reverse("erp-purchase-invoice-detail", args=[invoice_id]),
            {"notes": "keep existing supplier"},
            format="json",
        )
        assert patched.status_code == status.HTTP_200_OK, patched.data
        invoice = PurchaseInvoice.objects.get(id=invoice_id)
        assert invoice.supplier_id == active_supplier.id
        assert invoice.notes == "keep existing supplier"

    def test_cannot_change_existing_invoice_to_inactive_supplier(
        self, api_client, retailer_user, retailer, active_supplier, inactive_supplier, product
    ):
        api_client.force_authenticate(user=retailer_user)
        created = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(active_supplier, product, "INV-SWITCH"),
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        invoice_id = created.data["id"]

        switched = api_client.patch(
            reverse("erp-purchase-invoice-detail", args=[invoice_id]),
            {"supplier": inactive_supplier.id},
            format="json",
        )
        assert switched.status_code == status.HTTP_400_BAD_REQUEST, switched.data
        assert INACTIVE_SUPPLIER_MESSAGE in str(switched.data.get("supplier"))
        invoice = PurchaseInvoice.objects.get(id=invoice_id)
        assert invoice.supplier_id == active_supplier.id

    def test_cross_org_supplier_rejected_on_create(
        self, api_client, retailer_user, retailer, product
    ):
        from authentication.models import User
        from retailers.models import RetailerProfile
        from retailers.organization import ensure_organization_for_profile

        other_user = User.objects.create_user(
            username="oe100_other",
            email="oe100_other@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        other_shop = RetailerProfile.objects.create(
            user=other_user,
            shop_name="Other Org Shop",
            address_line1="9 Side",
            city="City",
            state="State",
            pincode="110009",
            is_active=True,
        )
        ensure_organization_for_profile(other_shop, name="Other Org")
        foreign = Supplier.objects.create(
            retailer=other_shop, company_name="Foreign Vendor", is_active=True
        )

        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(foreign, product, "INV-FOREIGN"),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert not PurchaseInvoice.objects.filter(invoice_number="INV-FOREIGN").exists()


# GET /erp/purchase-invoices/ with at least one row on the page: the caller's
# retailer for the queryset, the page count, the invoice page (supplier joined),
# and the caller's retailer again for the serializer context.
PI_LIST_FIXED_QUERIES = 4
# Per invoice the serializer walks that invoice's own children: refund_amount
# and net_amount each aggregate purchase_return, is_returned runs exists(), and
# the nested items page. Supplier is not in here — select_related('supplier')
# covers it — so this stays 4 however many distinct suppliers the page spans.
PI_LIST_PER_INVOICE_QUERIES = 4


def _seed_invoices(retailer, count):
    """One invoice per supplier, so an unjoined supplier read would show up."""
    for i in range(count):
        supplier = Supplier.objects.create(
            retailer=retailer, company_name=f"Vendor {i}"
        )
        PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number=f"INV-N1-{i}",
            invoice_date="2026-09-15",
            total_amount=Decimal("10.00"),
            paid_amount=Decimal("0.00"),
        )


@pytest.mark.django_db
class TestPurchaseInvoiceSupplierQueries:
    """The list serializer reads supplier.company_name on every row."""

    def test_list_query_budget(
        self, api_client, retailer_user, retailer, django_assert_num_queries
    ):
        _seed_invoices(retailer, 1)
        api_client.force_authenticate(user=retailer_user)
        with django_assert_num_queries(
            PI_LIST_FIXED_QUERIES + PI_LIST_PER_INVOICE_QUERIES
        ):
            resp = api_client.get(reverse("erp-purchase-invoice-list"))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert [row["supplier_name"] for row in resp.data["results"]] == ["Vendor 0"]

    def test_list_budget_is_flat_across_suppliers(
        self, api_client, retailer_user, retailer, django_assert_num_queries
    ):
        _seed_invoices(retailer, 3)
        api_client.force_authenticate(user=retailer_user)
        with django_assert_num_queries(
            PI_LIST_FIXED_QUERIES + 3 * PI_LIST_PER_INVOICE_QUERIES
        ):
            resp = api_client.get(reverse("erp-purchase-invoice-list"))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert sorted(row["supplier_name"] for row in resp.data["results"]) == [
            "Vendor 0",
            "Vendor 1",
            "Vendor 2",
        ]

    def test_list_reads_suppliers_without_per_row_query(
        self, api_client, retailer_user, retailer
    ):
        _seed_invoices(retailer, 3)
        api_client.force_authenticate(user=retailer_user)
        with CaptureQueriesContext(connection) as captured:
            resp = api_client.get(reverse("erp-purchase-invoice-list"))

        assert resp.status_code == status.HTTP_200_OK, resp.data
        standalone_supplier_reads = [
            q["sql"]
            for q in captured.captured_queries
            if 'FROM "supplier"' in q["sql"]
        ]
        assert standalone_supplier_reads == []


@pytest.mark.django_db
class TestPurchaseInvoiceSearchFields:
    def test_search_by_supplier_company_name(
        self, api_client, retailer_user, retailer
    ):
        _seed_invoices(retailer, 2)
        api_client.force_authenticate(user=retailer_user)

        resp = api_client.get(
            reverse("erp-purchase-invoice-list"), {"search": "Vendor 1"}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        names = [row["supplier_name"] for row in resp.data["results"]]
        assert names == ["Vendor 1"]

    def test_search_by_invoice_number(self, api_client, retailer_user, retailer):
        _seed_invoices(retailer, 2)
        api_client.force_authenticate(user=retailer_user)

        resp = api_client.get(
            reverse("erp-purchase-invoice-list"), {"search": "INV-N1-0"}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert [row["invoice_number"] for row in resp.data["results"]] == ["INV-N1-0"]

    def test_search_unknown_is_empty_not_field_error(
        self, api_client, retailer_user, retailer
    ):
        _seed_invoices(retailer, 1)
        api_client.force_authenticate(user=retailer_user)

        resp = api_client.get(
            reverse("erp-purchase-invoice-list"), {"search": "no-such-vendor"}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["results"] == []
