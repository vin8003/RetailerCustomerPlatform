from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from products.models import SupplierLedger
from products.serializers import PurchaseInvoiceSerializer
from retailers.models import Supplier


def _request_for(retailer):
    request = MagicMock()
    request.user = retailer.user
    return request


def _invoice_data(supplier, product, *, purchase_price):
    return {
        'supplier': supplier.id,
        'invoice_number': 'GST-PURCHASE-1',
        'invoice_date': '2026-09-15',
        'total_amount': '999.00',
        'paid_amount': '0.00',
        'payment_status': 'UNPAID',
        'items': [
            {
                'product': product.id,
                'quantity': '1.000',
                'purchase_price': purchase_price,
                'total': '999.00',
            }
        ],
    }


@pytest.mark.django_db
class TestPurchaseInvoiceTax:
    def test_create_snapshots_inclusive_gst_and_uses_rounded_total(
        self, retailer, product
    ):
        retailer.gst_number = '27ABCDE1234F1Z5'
        retailer.save(update_fields=['gst_number'])
        supplier = Supplier.objects.create(
            retailer=retailer,
            company_name='Maharashtra Supplier',
            gst_number='27ABCDE1234F1Z6',
        )
        product.gst_rate = Decimal('18.00')
        product.hsn_code = '10063010'
        product.save(update_fields=['gst_rate', 'hsn_code'])

        serializer = PurchaseInvoiceSerializer(
            data=_invoice_data(supplier, product, purchase_price='118.40'),
            context={'request': _request_for(retailer), 'retailer': retailer},
        )
        assert serializer.is_valid(), serializer.errors
        invoice = serializer.save(retailer=retailer)
        item = invoice.items.get()

        assert item.total == Decimal('118.40')
        assert item.taxable_value == Decimal('100.34')
        assert item.tax_amount == Decimal('18.06')
        assert item.gst_rate == Decimal('18.00')
        assert item.hsn_code == '10063010'
        assert item.tax_type == 'GST'
        assert invoice.taxable_amount == Decimal('100.34')
        assert invoice.tax_amount == Decimal('18.06')
        assert invoice.total_amount == Decimal('118.00')
        assert SupplierLedger.objects.get(
            reference_invoice=invoice, transaction_type='CREDIT'
        ).amount == Decimal('118.00')

    def test_update_rebuilds_tax_snapshots_and_resolves_igst(
        self, retailer, product
    ):
        retailer.gst_number = '27ABCDE1234F1Z5'
        retailer.save(update_fields=['gst_number'])
        local_supplier = Supplier.objects.create(
            retailer=retailer,
            company_name='Local Supplier',
            gst_number='27ABCDE1234F1Z6',
        )
        interstate_supplier = Supplier.objects.create(
            retailer=retailer,
            company_name='Interstate Supplier',
            gst_number='29ABCDE1234F1Z6',
        )
        product.gst_rate = Decimal('18.00')
        product.hsn_code = '10063010'
        product.save(update_fields=['gst_rate', 'hsn_code'])

        create_serializer = PurchaseInvoiceSerializer(
            data=_invoice_data(local_supplier, product, purchase_price='118.00'),
            context={'request': _request_for(retailer), 'retailer': retailer},
        )
        assert create_serializer.is_valid(), create_serializer.errors
        invoice = create_serializer.save(retailer=retailer)

        update_serializer = PurchaseInvoiceSerializer(
            invoice,
            data=_invoice_data(
                interstate_supplier, product, purchase_price='236.00'
            ),
            context={'request': _request_for(retailer), 'retailer': retailer},
        )
        assert update_serializer.is_valid(), update_serializer.errors
        invoice = update_serializer.save()
        item = invoice.items.get()

        assert item.total == Decimal('236.00')
        assert item.taxable_value == Decimal('200.00')
        assert item.tax_amount == Decimal('36.00')
        assert item.tax_type == 'IGST'
        assert invoice.taxable_amount == Decimal('200.00')
        assert invoice.tax_amount == Decimal('36.00')
        assert invoice.total_amount == Decimal('236.00')
        assert SupplierLedger.objects.get(
            reference_invoice=invoice, transaction_type='CREDIT'
        ).amount == Decimal('236.00')

    def test_scalar_patch_cannot_override_calculated_total(
        self, retailer, product
    ):
        supplier = Supplier.objects.create(
            retailer=retailer,
            company_name='Authoritative Total Supplier',
        )
        serializer = PurchaseInvoiceSerializer(
            data=_invoice_data(supplier, product, purchase_price='118.00'),
            context={'request': _request_for(retailer), 'retailer': retailer},
        )
        assert serializer.is_valid(), serializer.errors
        invoice = serializer.save(retailer=retailer)

        patch_serializer = PurchaseInvoiceSerializer(
            invoice,
            data={'total_amount': '1.00'},
            partial=True,
            context={'request': _request_for(retailer), 'retailer': retailer},
        )
        assert patch_serializer.is_valid(), patch_serializer.errors
        patch_serializer.save()
        invoice.refresh_from_db()

        assert invoice.total_amount == Decimal('118.00')

    def test_representation_exposes_read_only_tax_snapshots(
        self, retailer, product
    ):
        supplier = Supplier.objects.create(
            retailer=retailer,
            company_name='Snapshot Supplier',
        )
        product.gst_rate = Decimal('18.00')
        product.hsn_code = '10063010'
        product.save(update_fields=['gst_rate', 'hsn_code'])
        serializer = PurchaseInvoiceSerializer(
            data=_invoice_data(supplier, product, purchase_price='118.00'),
            context={'request': _request_for(retailer), 'retailer': retailer},
        )
        assert serializer.is_valid(), serializer.errors
        invoice = serializer.save(retailer=retailer)

        data = PurchaseInvoiceSerializer(invoice).data

        assert data['taxable_amount'] == '100.00'
        assert data['tax_amount'] == '18.00'
        assert data['items'][0]['hsn_code'] == '10063010'
        assert data['items'][0]['gst_rate'] == '18.00'
        assert data['items'][0]['taxable_value'] == '100.00'
        assert data['items'][0]['tax_amount'] == '18.00'
        assert data['items'][0]['tax_type'] == 'GST'
