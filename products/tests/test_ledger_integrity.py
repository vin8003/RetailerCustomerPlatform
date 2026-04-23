import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import PurchaseInvoice, PurchaseItem, SupplierLedger, Product
from retailers.models import Supplier

@pytest.mark.django_db
class TestLedgerIntegrity:
    """
    Test integrity of Supplier Ledger and Invoice deletion
    """

    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="Integrity Supplier"
        )

    def test_delete_purchase_invoice_reverses_everything(self, api_client, retailer_user, retailer, supplier, product):
        api_client.force_authenticate(user=retailer_user)
        
        # 1. Create Invoice via manual objects (simulating API create)
        invoice = PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number="DEL-INV",
            invoice_date="2026-04-23",
            total_amount=Decimal("500.00")
        )
        PurchaseItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=5,
            purchase_price=Decimal("100.00"),
            total=Decimal("500.00")
        )
        SupplierLedger.objects.create(
            supplier=supplier,
            amount=Decimal("500.00"),
            transaction_type='CREDIT',
            reference_invoice=invoice,
            date="2026-04-23"
        )
        
        # Initial stock was 50, now 55 (manually simulate view logic as seen in api_erp_views)
        product.quantity += 5
        product.save()
        
        # Verify supplier balance
        supplier.refresh_from_db()
        assert supplier.balance_due == Decimal("500.00")
        
        # 2. Delete Invoice via API
        url = reverse("erp-purchase-invoice-detail", args=[invoice.id])
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        
        # 3. Verify Stock Reversal
        product.refresh_from_db()
        assert product.quantity == 50
        
        # 4. Verify Ledger Reversal
        assert SupplierLedger.objects.filter(reference_invoice=invoice).count() == 0
        
        # 5. Verify Supplier Balance Reversal
        supplier.refresh_from_db()
        assert supplier.balance_due == Decimal("0.00")

    def test_manual_payment_entry(self, api_client, retailer_user, retailer, supplier):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("erp-supplier-ledger-list")
        
        # Create an unpaid balance first
        SupplierLedger.objects.create(supplier=supplier, amount=1000, transaction_type='CREDIT', date="2026-04-23")
        
        # Make a payment (DEBIT)
        data = {
            "supplier": supplier.id,
            "amount": 400.00,
            "transaction_type": "DEBIT",
            "date": "2026-04-23",
            "payment_mode": "cash"
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        supplier.refresh_from_db()
        assert supplier.balance_due == Decimal("600.00")
