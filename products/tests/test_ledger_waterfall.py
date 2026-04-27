import pytest
from decimal import Decimal
from django.utils import timezone
from products.models import PurchaseInvoice, SupplierLedger
from retailers.models import Supplier

@pytest.mark.django_db
class TestLedgerWaterfall:
    """
    Test the FIFO (Waterfall) payment allocation logic in products/signals.py
    """

    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="Waterfall Supplier",
            contact_person="Jane Doe"
        )

    def test_payment_allocation_fifo(self, retailer, supplier):
        # 1. Create two invoices
        inv1 = PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number="INV-1",
            invoice_date=timezone.now().date(),
            total_amount=Decimal("1000.00")
        )
        inv2 = PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number="INV-2",
            invoice_date=timezone.now().date(),
            total_amount=Decimal("1000.00")
        )
        
        # 2. Add CREDIT entries for these invoices
        SupplierLedger.objects.create(
            supplier=supplier, 
            amount=Decimal("1000.00"), 
            transaction_type='CREDIT', 
            reference_invoice=inv1, 
            date=timezone.now().date()
        )
        SupplierLedger.objects.create(
            supplier=supplier, 
            amount=Decimal("1000.00"), 
            transaction_type='CREDIT', 
            reference_invoice=inv2, 
            date=timezone.now().date()
        )
        
        # 3. Add a payment (DEBIT) of 1500
        payment = SupplierLedger.objects.create(
            supplier=supplier,
            amount=Decimal("1500.00"),
            transaction_type='DEBIT',
            date=timezone.now().date(),
            notes="Partial Bulk Payment"
        )
        
        inv1.refresh_from_db()
        inv2.refresh_from_db()
        
        # inv1 should be fully paid (1000)
        assert inv1.paid_amount == Decimal("1000.00")
        assert inv1.payment_status == 'PAID'
        
        # inv2 should be partially paid (500)
        assert inv2.paid_amount == Decimal("500.00")
        assert inv2.payment_status == 'PARTIAL'
        
        # Supplier balance should be 500 (Debt)
        supplier.refresh_from_db()
        assert supplier.balance_due == Decimal("500.00")
        
        # 4. Delete payment
        payment.delete()
        
        inv1.refresh_from_db()
        inv2.refresh_from_db()
        assert inv1.payment_status == 'UNPAID'
        assert inv2.payment_status == 'UNPAID'
        assert inv1.paid_amount == 0
        
        supplier.refresh_from_db()
        assert supplier.balance_due == Decimal("2000.00")
