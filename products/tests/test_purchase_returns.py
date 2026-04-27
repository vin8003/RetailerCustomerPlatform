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
