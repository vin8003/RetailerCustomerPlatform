"""
KAN-75: stock mismatch — ledger jumps, product/batch drift, log replay repair.
"""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from django.core.management import call_command
from django.urls import reverse
from rest_framework import status

from products.inventory_service import replay_quantity_from_logs, reconcile_product_from_logs
from products.models import Product, ProductBatch, ProductInventoryLog, PurchaseInvoice
from products.serializers import PurchaseInvoiceSerializer
from retailers.models import Supplier


@pytest.mark.django_db
class TestPOSProductLevelLedger:
    """POS must log product.quantity, not batch.quantity, as ledger balance."""

    def test_pos_batch_sale_logs_product_balance(self, api_client, retailer_user, retailer, category, brand):
        api_client.force_authenticate(user=retailer_user)

        product = Product.objects.create(
            retailer=retailer,
            name='KAN75 Batch Product',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            has_batches=True,
            track_inventory=True,
            quantity=Decimal('60'),
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='INITIAL-STOCK',
            price=Decimal('5.00'),
            quantity=Decimal('9'),
            is_active=True,
        )
        empty_batch = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='',
            price=Decimal('5.00'),
            quantity=Decimal('0'),
            is_active=True,
        )
        product.sync_inventory_from_batches()

        url = reverse('create_pos_order')
        response = api_client.post(
            url,
            {
                'subtotal': 20.0,
                'total_amount': 20.0,
                'items': [
                    {
                        'product_id': product.id,
                        'batch_id': empty_batch.id,
                        'quantity': 4,
                        'unit_price': 5.0,
                    }
                ],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED

        log = ProductInventoryLog.objects.filter(product=product, log_type='sold').last()
        assert log.batch_id == empty_batch.id
        assert log.previous_quantity == Decimal('9')
        assert log.new_quantity == Decimal('5')
        assert log.quantity_change == Decimal('-4')

        product.refresh_from_db()
        assert product.quantity == Decimal('5')


@pytest.mark.django_db
class TestPurchaseBatchSync:
    """Purchase inward must update batches when has_batches=True."""

    def test_purchase_inward_updates_batch_sum(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name='KAN75 Purchase Product',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            has_batches=True,
            track_inventory=True,
            quantity=Decimal('2'),
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='INITIAL-STOCK',
            price=Decimal('5.00'),
            quantity=Decimal('2'),
            is_active=True,
        )

        supplier = Supplier.objects.create(retailer=retailer, company_name='KAN75 Supplier')
        request = MagicMock()
        request.user = retailer.user

        serializer = PurchaseInvoiceSerializer(
            data={
                'supplier': supplier.id,
                'invoice_number': 'KAN75-INV-1',
                'invoice_date': '2026-08-14',
                'total_amount': '321.00',
                'paid_amount': '0.00',
                'payment_status': 'UNPAID',
                'items': [
                    {
                        'product': product.id,
                        'quantity': 72,
                        'purchase_price': '4.46',
                        'total': '321.00',
                    }
                ],
            },
            context={'request': request, 'retailer': retailer},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save(retailer=retailer)

        product.refresh_from_db()
        batch_sum = sum(
            b.quantity for b in product.batches.filter(is_active=True)
        )
        assert product.quantity == Decimal('74')
        assert batch_sum == product.quantity


@pytest.mark.django_db
class TestLogReplay:
    """Replay matches KAN-75 product 111 scenario: 60 then -4-7-12-1 = 36."""

    def test_replay_product_111_scenario(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name='KAN75 Replay Product',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            has_batches=True,
            track_inventory=True,
            quantity=Decimal('-15'),
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='INITIAL-STOCK',
            price=Decimal('5.00'),
            quantity=Decimal('9'),
            is_active=True,
        )
        phantom = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='',
            price=Decimal('5.00'),
            quantity=Decimal('-24'),
            is_active=True,
        )

        ProductInventoryLog.objects.create(
            product=product,
            log_type='sold',
            quantity_change=Decimal('-1'),
            previous_quantity=Decimal('61'),
            new_quantity=Decimal('60'),
            reason='POS Sale: Order #ORD-1786857632-526',
        )
        for qty, new_bal in [
            (Decimal('-4'), Decimal('-4')),
            (Decimal('-7'), Decimal('-11')),
            (Decimal('-12'), Decimal('-23')),
            (Decimal('-1'), Decimal('-24')),
        ]:
            ProductInventoryLog.objects.create(
                product=product,
                batch=phantom,
                log_type='sold',
                quantity_change=qty,
                previous_quantity=new_bal - qty,
                new_quantity=new_bal,
                reason='POS Sale batch-level',
            )

        assert replay_quantity_from_logs(product) == Decimal('36')

        result = reconcile_product_from_logs(product, dry_run=True)
        assert result['replayed_quantity'] == Decimal('36')
        assert result['current_quantity'] == Decimal('-15')
        assert result['delta'] == Decimal('51')

        applied = reconcile_product_from_logs(product, dry_run=False)
        product.refresh_from_db()
        initial = product.batches.get(batch_number='INITIAL-STOCK')
        phantom.refresh_from_db()

        assert applied['applied_quantity'] == Decimal('36')
        assert product.quantity == Decimal('36')
        assert initial.quantity == Decimal('36')
        assert phantom.quantity == Decimal('0')
        assert phantom.is_active is False


@pytest.mark.django_db
class TestReconcileCommand:
    def test_dry_run_by_default(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name='KAN75 Command Product',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            track_inventory=True,
            quantity=Decimal('10'),
        )
        ProductInventoryLog.objects.create(
            product=product,
            log_type='added',
            quantity_change=Decimal('10'),
            previous_quantity=Decimal('0'),
            new_quantity=Decimal('10'),
            reason='Initial',
        )

        call_command('reconcile_inventory_from_logs', f'--product-id={product.id}')
        product.refresh_from_db()
        assert product.quantity == Decimal('10')
