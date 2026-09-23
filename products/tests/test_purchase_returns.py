import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import Product, PurchaseInvoice, PurchaseItem, SupplierLedger
from returns.models import PurchaseReturn, PurchaseReturnItem
from retailers.models import Supplier

@pytest.mark.django_db
class TestPurchaseReturns:
    """
    Test cases for Purchase Returns and Supplier Ledger impact
    """

    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="Test Supplier",
            contact_person="John Doe",
            phone_number="9876543210"
        )

    @pytest.fixture
    def purchase_invoice(self, retailer, supplier, product):
        invoice = PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number="INV-001",
            invoice_date="2026-04-23",
            total_amount=Decimal("1000.00"),
            payment_status="UNPAID"
        )
        PurchaseItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=10,
            purchase_price=Decimal("100.00"),
            total=Decimal("1000.00")
        )
        # Manually update product stock as normally done in view/serializer
        product.quantity += 10
        product.save()
        
        # Credit supplier ledger
        SupplierLedger.objects.create(
            supplier=supplier,
            date="2026-04-23",
            amount=Decimal("1000.00"),
            transaction_type="CREDIT",
            reference_invoice=invoice
        )
        return invoice

    def test_create_purchase_return_api(self, api_client, retailer_user, retailer, supplier, purchase_invoice, product):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("purchase-return-list")
        
        purchase_item = purchase_invoice.items.first()
        initial_qty = product.quantity
        
        data = {
            "supplier_id": supplier.id,
            "invoice_id": purchase_invoice.id,
            "notes": "Damaged goods",
            "items": [
                {
                    "product_id": product.id,
                    "purchase_item_id": purchase_item.id,
                    "quantity": 2,
                    "purchase_price": 100.00
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        # Verify return record
        assert PurchaseReturn.objects.count() == 1
        ret = PurchaseReturn.objects.first()
        assert ret.total_amount == Decimal("200.00")
        
        # Verify stock deduction
        product.refresh_from_db()
        assert product.quantity == initial_qty - 2
        
        # Verify Supplier Ledger (DEBIT entry)
        ledger_debit = SupplierLedger.objects.filter(supplier=supplier, transaction_type="DEBIT").first()
        assert ledger_debit is not None
        assert ledger_debit.amount == Decimal("200.00")
        assert "Purchase Return" in ledger_debit.notes

    def test_purchase_return_exceeds_quantity(self, api_client, retailer_user, retailer, supplier, purchase_invoice, product):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("purchase-return-list")
        
        purchase_item = purchase_invoice.items.first()
        
        data = {
            "supplier_id": supplier.id,
            "invoice_id": purchase_invoice.id,
            "items": [
                {
                    "product_id": product.id,
                    "purchase_item_id": purchase_item.id,
                    "quantity": 15, # Only 10 purchased
                    "purchase_price": 100.00
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot return" in response.data["error"]

    def test_get_invoice_items_for_return(self, api_client, retailer_user, retailer, purchase_invoice):
        api_client.force_authenticate(user=retailer_user)
        # The action is 'get_invoice_items' on PurchaseReturnViewSet
        url = reverse("purchase-return-get-invoice-items")
        
        response = api_client.get(url, {"invoice_id": purchase_invoice.id})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["quantity"] == 10
        assert response.data[0]["available_qty"] == 10

    def test_purchase_return_reverses_inclusive_tax_from_purchase_item_snapshot(
        self, api_client, retailer_user, supplier, purchase_invoice, product
    ):
        api_client.force_authenticate(user=retailer_user)
        purchase_item = purchase_invoice.items.first()
        purchase_item.hsn_code = "10063010"
        purchase_item.gst_rate = Decimal("5.00")
        purchase_item.tax_type = "IGST"
        purchase_item.purchase_price = Decimal("105.00")
        purchase_item.save()
        product.hsn_code = "DIFFERENT"
        product.gst_rate = Decimal("18.00")
        product.save()

        response = api_client.post(
            reverse("purchase-return-list"),
            {
                "supplier_id": supplier.id,
                "invoice_id": purchase_invoice.id,
                "items": [{
                    "product_id": product.id,
                    "purchase_item_id": purchase_item.id,
                    "quantity": 2,
                    "purchase_price": "105.00",
                }],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        purchase_return = PurchaseReturn.objects.get()
        return_item = purchase_return.items.get()
        assert purchase_return.total_amount == Decimal("210.00")
        assert purchase_return.taxable_amount == Decimal("200.00")
        assert purchase_return.tax_amount == Decimal("10.00")
        assert return_item.hsn_code == "10063010"
        assert return_item.gst_rate == Decimal("5.00")
        assert return_item.tax_type == "IGST"
        assert return_item.taxable_value == Decimal("200.00")
        assert return_item.tax_amount == Decimal("10.00")
        ledger = SupplierLedger.objects.filter(
            supplier=supplier, transaction_type="DEBIT"
        ).latest("id")
        assert ledger.amount == Decimal("210.00")

    def test_purchase_return_falls_back_to_product_tax_when_purchase_item_missing(
        self, api_client, retailer_user, supplier, purchase_invoice, product
    ):
        api_client.force_authenticate(user=retailer_user)
        purchase_item = purchase_invoice.items.first()
        purchase_item.hsn_code = "10063010"
        purchase_item.gst_rate = Decimal("5.00")
        purchase_item.save()
        product.hsn_code = "22021000"
        product.gst_rate = Decimal("18.00")
        product.save()

        response = api_client.post(
            reverse("purchase-return-list"),
            {
                "supplier_id": supplier.id,
                "invoice_id": purchase_invoice.id,
                "items": [{
                    "product_id": product.id,
                    "quantity": 2,
                    "purchase_price": "118.00",
                }],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        purchase_return = PurchaseReturn.objects.get()
        return_item = purchase_return.items.get()
        assert purchase_return.total_amount == Decimal("236.00")
        assert purchase_return.taxable_amount == Decimal("200.00")
        assert purchase_return.tax_amount == Decimal("36.00")
        assert return_item.hsn_code == "22021000"
        assert return_item.gst_rate == Decimal("18.00")
        assert return_item.tax_type == "GST"
        assert return_item.purchase_item is None

    def test_get_invoice_items_exposes_tax_snapshot(
        self, api_client, retailer_user, purchase_invoice
    ):
        api_client.force_authenticate(user=retailer_user)
        purchase_item = purchase_invoice.items.first()
        purchase_item.hsn_code = "10063010"
        purchase_item.gst_rate = Decimal("5.00")
        purchase_item.tax_type = "GST"
        purchase_item.save()

        response = api_client.get(
            reverse("purchase-return-get-invoice-items"),
            {"invoice_id": purchase_invoice.id},
        )

        item = response.data[0]
        assert item["hsn_code"] == "10063010"
        assert Decimal(item["gst_rate"]) == Decimal("5.00")
        assert item["tax_type"] == "GST"
