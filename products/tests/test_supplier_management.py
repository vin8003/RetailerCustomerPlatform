import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import PurchaseInvoice, PurchaseItem, SupplierLedger
from retailers.models import Supplier
from returns.models import PurchaseReturn


def _invoice_payload(supplier, product, invoice_number="INV-KAN78"):
    return {
        "supplier": supplier.id,
        "invoice_number": invoice_number,
        "invoice_date": "2026-08-23",
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


def _result_ids(response):
    data = response.data["results"] if isinstance(response.data, dict) else response.data
    return [row["id"] for row in data]


def _auth(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


@pytest.mark.django_db
class TestSupplierManagement:
    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="ABC Foods",
            contact_person="Ravi Kumar",
            phone_number="9876543210",
        )

    def test_patch_updates_company_name_without_phone(
        self, api_client, retailer_user, supplier
    ):
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-detail", args=[supplier.id])
        response = api_client.patch(
            url,
            {"company_name": "ABC Foods Pvt", "phone_number": ""},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        supplier.refresh_from_db()
        assert supplier.company_name == "ABC Foods Pvt"
        assert supplier.phone_number == ""

    def test_deactivate_succeeds_when_invoice_and_ledger_exist(
        self, api_client, retailer_user, retailer, supplier
    ):
        PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number="INV-KAN78",
            invoice_date="2026-08-23",
            total_amount=Decimal("100.00"),
        )
        SupplierLedger.objects.create(
            supplier=supplier,
            date="2026-08-23",
            amount=Decimal("100.00"),
            transaction_type="CREDIT",
        )
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-detail", args=[supplier.id])
        response = api_client.patch(url, {"is_active": False}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_active"] is False
        supplier.refresh_from_db()
        assert supplier.is_active is False

        get_res = api_client.get(url)
        assert get_res.status_code == status.HTTP_200_OK
        assert get_res.data["id"] == supplier.id

        list_res = api_client.get(reverse("erp-supplier-list"))
        assert supplier.id in _result_ids(list_res)

    def test_reactivate_sets_is_active_true(self, api_client, retailer_user, supplier):
        supplier.is_active = False
        supplier.save(update_fields=["is_active"])
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-detail", args=[supplier.id])
        response = api_client.patch(url, {"is_active": True}, format="json")
        assert response.status_code == status.HTTP_200_OK
        supplier.refresh_from_db()
        assert supplier.is_active is True

    def test_list_is_active_true_omits_inactive(
        self, api_client, retailer_user, retailer, supplier
    ):
        inactive = Supplier.objects.create(
            retailer=retailer,
            company_name="Old Van",
            is_active=False,
        )
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-list")

        filtered = api_client.get(url, {"is_active": "true"})
        assert filtered.status_code == status.HTTP_200_OK
        ids = _result_ids(filtered)
        assert supplier.id in ids
        assert inactive.id not in ids

        unfiltered = api_client.get(url)
        assert unfiltered.status_code == status.HTTP_200_OK
        all_ids = _result_ids(unfiltered)
        assert supplier.id in all_ids
        assert inactive.id in all_ids

        inactive_only = api_client.get(url, {"is_active": "false"})
        assert inactive_only.status_code == status.HTTP_200_OK
        inactive_ids = _result_ids(inactive_only)
        assert supplier.id not in inactive_ids
        assert inactive.id in inactive_ids

    def test_delete_unused_supplier_succeeds(self, api_client, retailer_user, supplier):
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-detail", args=[supplier.id])
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Supplier.objects.filter(id=supplier.id).exists()

    def test_delete_blocked_when_invoice_exists(
        self, api_client, retailer_user, retailer, supplier
    ):
        PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number="INV-KEEP",
            invoice_date="2026-08-23",
            total_amount=Decimal("50.00"),
        )
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-detail", args=[supplier.id])
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Supplier.objects.filter(id=supplier.id).exists()

    def test_delete_blocked_when_ledger_exists(
        self, api_client, retailer_user, supplier
    ):
        SupplierLedger.objects.create(
            supplier=supplier,
            date="2026-08-23",
            amount=Decimal("25.00"),
            transaction_type="DEBIT",
        )
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-detail", args=[supplier.id])
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Supplier.objects.filter(id=supplier.id).exists()

    def test_delete_blocked_when_purchase_return_exists(
        self, api_client, retailer_user, retailer, supplier
    ):
        PurchaseReturn.objects.create(
            retailer=retailer,
            supplier=supplier,
            total_amount=Decimal("10.00"),
        )
        _auth(api_client, retailer_user)
        url = reverse("erp-supplier-detail", args=[supplier.id])
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Supplier.objects.filter(id=supplier.id).exists()

    def test_search_by_company_name_returns_200(
        self, api_client, retailer_user, supplier
    ):
        _auth(api_client, retailer_user)
        response = api_client.get(
            reverse("erp-supplier-list"), {"search": "ABC"}
        )
        assert response.status_code == status.HTTP_200_OK
        assert supplier.id in _result_ids(response)


@pytest.mark.django_db
class TestInactiveSupplierTransactions:
    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="Active Dist",
        )

    @pytest.fixture
    def inactive_supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="Closed Dist",
            is_active=False,
        )

    def test_post_purchase_invoice_rejects_inactive_supplier(
        self, api_client, retailer_user, retailer, inactive_supplier, product
    ):
        _auth(api_client, retailer_user)
        response = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(inactive_supplier, product),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "supplier" in response.data
        assert PurchaseInvoice.objects.count() == 0

    def test_patch_invoice_keeps_inactive_supplier(
        self, api_client, retailer_user, retailer, supplier, product
    ):
        _auth(api_client, retailer_user)
        create_res = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(supplier, product, invoice_number="INV-KEEP-INACTIVE"),
            format="json",
        )
        assert create_res.status_code == status.HTTP_201_CREATED, create_res.data
        invoice_id = create_res.data["id"]
        item = create_res.data["items"][0]

        supplier.is_active = False
        supplier.save(update_fields=["is_active"])

        patch_res = api_client.patch(
            reverse("erp-purchase-invoice-detail", args=[invoice_id]),
            {
                "supplier": supplier.id,
                "invoice_number": "INV-KEEP-INACTIVE",
                "invoice_date": "2026-08-23",
                "items": [
                    {
                        "product": product.id,
                        "quantity": 8,
                        "purchase_price": "10.00",
                        "total": "80.00",
                    }
                ],
            },
            format="json",
        )
        assert patch_res.status_code == status.HTTP_200_OK, patch_res.data
        assert patch_res.data["supplier"] == supplier.id
        assert item["id"]  # original create succeeded

    def test_patch_invoice_rejects_switch_to_inactive_supplier(
        self, api_client, retailer_user, retailer, supplier, inactive_supplier, product
    ):
        _auth(api_client, retailer_user)
        create_res = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(supplier, product, invoice_number="INV-SWITCH"),
            format="json",
        )
        assert create_res.status_code == status.HTTP_201_CREATED, create_res.data
        invoice_id = create_res.data["id"]

        patch_res = api_client.patch(
            reverse("erp-purchase-invoice-detail", args=[invoice_id]),
            {
                "supplier": inactive_supplier.id,
                "invoice_number": "INV-SWITCH",
                "invoice_date": "2026-08-23",
                "items": [
                    {
                        "product": product.id,
                        "quantity": 10,
                        "purchase_price": "10.00",
                        "total": "100.00",
                    }
                ],
            },
            format="json",
        )
        assert patch_res.status_code == status.HTTP_400_BAD_REQUEST
        assert "supplier" in patch_res.data

    def test_ledger_debit_allowed_on_inactive_supplier(
        self, api_client, retailer_user, inactive_supplier
    ):
        SupplierLedger.objects.create(
            supplier=inactive_supplier,
            date="2026-08-23",
            amount=Decimal("1000.00"),
            transaction_type="CREDIT",
        )
        _auth(api_client, retailer_user)
        response = api_client.post(
            reverse("erp-supplier-ledger-list"),
            {
                "supplier": inactive_supplier.id,
                "amount": "400.00",
                "transaction_type": "DEBIT",
                "date": "2026-08-23",
                "payment_mode": "cash",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data

    def test_purchase_return_allowed_on_inactive_supplier(
        self, api_client, retailer_user, retailer, inactive_supplier, product
    ):
        invoice = PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=inactive_supplier,
            invoice_number="INV-RET-INACTIVE",
            invoice_date="2026-08-23",
            total_amount=Decimal("1000.00"),
            payment_status="UNPAID",
        )
        purchase_item = PurchaseItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=10,
            purchase_price=Decimal("100.00"),
            total=Decimal("1000.00"),
        )
        product.quantity += 10
        product.save()
        SupplierLedger.objects.create(
            supplier=inactive_supplier,
            date="2026-08-23",
            amount=Decimal("1000.00"),
            transaction_type="CREDIT",
            reference_invoice=invoice,
        )
        _auth(api_client, retailer_user)
        response = api_client.post(
            reverse("purchase-return-list"),
            {
                "supplier_id": inactive_supplier.id,
                "invoice_id": invoice.id,
                "notes": "Damaged",
                "items": [
                    {
                        "product_id": product.id,
                        "purchase_item_id": purchase_item.id,
                        "quantity": 2,
                        "purchase_price": 100.00,
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert PurchaseReturn.objects.filter(supplier=inactive_supplier).count() == 1
