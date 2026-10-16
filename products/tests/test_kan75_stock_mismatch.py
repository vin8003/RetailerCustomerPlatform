"""
KAN-75: stock mismatch — ledger jumps, product/batch drift, log replay repair.

Local-only tests. Production data for product 111 is reconstructed here from
the live query dump; these tests never connect to the production database.
"""
import io
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework import status

from products.inventory_service import (
    apply_stock_decrease,
    apply_stock_increase,
    product_level_log_balances,
    reconcile_product_from_logs,
    replay_inventory_state,
    replay_quantity_from_logs,
)
from products.models import Product, ProductBatch, ProductInventoryLog, PurchaseInvoice
from products.serializers import PurchaseInvoiceSerializer
from retailers.models import Supplier


# Signed movements from buyez_db product 111 (PARLE KRACK JACK 28GM).
# Replay of quantity_change from first previous_quantity=100 ends at 36.
PRODUCT_111_LOGS = [
    ('removed', Decimal('89'), Decimal('100'), Decimal('11'), None),
    ('added', Decimal('144'), Decimal('11'), Decimal('155'), None),
    ('sold', Decimal('-5'), Decimal('155'), Decimal('150'), None),
    ('sold', Decimal('-4'), Decimal('150'), Decimal('146'), None),
    ('sold', Decimal('-1'), Decimal('146'), Decimal('145'), None),
    ('sold', Decimal('-1'), Decimal('145'), Decimal('144'), None),
    ('sold', Decimal('-4'), Decimal('144'), Decimal('140'), None),
    ('sold', Decimal('-12'), Decimal('140'), Decimal('128'), None),
    ('sold', Decimal('-2'), Decimal('128'), Decimal('126'), None),
    ('sold', Decimal('-6'), Decimal('126'), Decimal('120'), None),
    ('sold', Decimal('-12'), Decimal('120'), Decimal('108'), None),
    ('sold', Decimal('-24'), Decimal('108'), Decimal('84'), None),
    ('sold', Decimal('-1'), Decimal('84'), Decimal('83'), None),
    ('sold', Decimal('-12'), Decimal('83'), Decimal('71'), None),
    ('removed', Decimal('30'), Decimal('71'), Decimal('41'), None),
    ('sold', Decimal('-1'), Decimal('41'), Decimal('40'), None),
    ('sold', Decimal('-2'), Decimal('40'), Decimal('38'), None),
    ('sold', Decimal('-1'), Decimal('38'), Decimal('37'), None),
    ('sold', Decimal('-12'), Decimal('37'), Decimal('25'), None),
    ('sold', Decimal('-4'), Decimal('25'), Decimal('21'), None),
    ('sold', Decimal('-6'), Decimal('21'), Decimal('15'), None),
    ('sold', Decimal('-4'), Decimal('15'), Decimal('11'), None),
    ('removed', Decimal('2'), Decimal('11'), Decimal('9'), None),
    ('sold', Decimal('-2'), Decimal('9'), Decimal('7'), None),
    ('sold', Decimal('-1'), Decimal('7'), Decimal('6'), None),
    ('sold', Decimal('-4'), Decimal('6'), Decimal('2'), None),
    ('added', Decimal('72'), Decimal('2'), Decimal('74'), None),
    ('sold', Decimal('-1'), Decimal('74'), Decimal('73'), None),
    ('sold', Decimal('-12'), Decimal('73'), Decimal('61'), None),
    ('sold', Decimal('-1'), Decimal('61'), Decimal('60'), None),
    ('sold', Decimal('-4'), Decimal('0'), Decimal('-4'), 'phantom'),
    ('sold', Decimal('-7'), Decimal('-4'), Decimal('-11'), 'phantom'),
    ('sold', Decimal('-12'), Decimal('-11'), Decimal('-23'), 'phantom'),
    ('sold', Decimal('-1'), Decimal('-23'), Decimal('-24'), 'phantom'),
]


def _batched_product(retailer, category, brand, *, name='KAN75 SKU', quantity=Decimal('10')):
    product = Product.objects.create(
        retailer=retailer,
        name=name,
        category=category,
        brand=brand,
        price=Decimal('5.00'),
        has_batches=True,
        track_inventory=True,
        quantity=quantity,
    )
    initial = ProductBatch.objects.create(
        product=product,
        retailer=retailer,
        batch_number='INITIAL-STOCK',
        price=Decimal('5.00'),
        quantity=quantity,
        is_active=True,
    )
    return product, initial


def _write_logs(product, rows, phantom=None):
    for log_type, change, prev, new, batch_tag in rows:
        ProductInventoryLog.objects.create(
            product=product,
            batch=phantom if batch_tag == 'phantom' else None,
            log_type=log_type,
            quantity_change=change,
            previous_quantity=prev,
            new_quantity=new,
            reason='replicated production log',
        )


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
    """Purchase inward must update batches when has_batches=True.

    Serializer tests use MagicMock only for request; the mock must expose
    `.user` (a real User). No other request attributes are read.
    """

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


@pytest.mark.django_db
class TestProduct111ProductionReplica:
    """Replay the exact production log chain for PARLE KRACK JACK 28GM (id 111)."""

    def _seed(self, retailer, category, brand):
        product, initial = _batched_product(
            retailer, category, brand,
            name='PARLE KRACK JACK BISCUITS 28GM',
            quantity=Decimal('-15'),
        )
        initial.quantity = Decimal('9')
        initial.save(update_fields=['quantity'])
        phantom = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='',
            price=Decimal('5.00'),
            quantity=Decimal('-24'),
            is_active=True,
        )
        _write_logs(product, PRODUCT_111_LOGS, phantom=phantom)
        return product, initial, phantom

    def test_replay_ignores_batch_level_new_quantity(self, retailer, category, brand):
        product, _initial, _phantom = self._seed(retailer, category, brand)
        last = ProductInventoryLog.objects.filter(product=product).order_by('id').last()
        assert last.new_quantity == Decimal('-24')
        assert replay_quantity_from_logs(product) == Decimal('36')

    def test_dry_run_does_not_write(self, retailer, category, brand):
        product, initial, phantom = self._seed(retailer, category, brand)
        result = reconcile_product_from_logs(product, dry_run=True)
        product.refresh_from_db()
        initial.refresh_from_db()
        phantom.refresh_from_db()
        assert result['replayed_quantity'] == Decimal('36')
        assert result['delta'] == Decimal('51')
        assert product.quantity == Decimal('-15')
        assert initial.quantity == Decimal('9')
        assert phantom.is_active is True
        assert not ProductInventoryLog.objects.filter(
            product=product, reason__contains='KAN-75'
        ).exists()

    def test_apply_repairs_header_and_deactivates_phantom(self, retailer, category, brand):
        product, initial, phantom = self._seed(retailer, category, brand)
        reconcile_product_from_logs(product, dry_run=False)
        product.refresh_from_db()
        initial.refresh_from_db()
        phantom.refresh_from_db()
        assert product.quantity == Decimal('36')
        assert initial.quantity == Decimal('36')
        assert phantom.quantity == Decimal('0')
        assert phantom.is_active is False
        repair_log = ProductInventoryLog.objects.filter(
            product=product, reason__contains='KAN-75'
        ).last()
        assert repair_log is not None
        assert repair_log.previous_quantity == Decimal('-15')
        assert repair_log.new_quantity == Decimal('36')

    def test_apply_keeps_real_secondary_batch(self, retailer, category, brand):
        product, initial, phantom = self._seed(retailer, category, brand)
        real = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='B-REAL',
            price=Decimal('5.00'),
            quantity=Decimal('5'),
            is_active=True,
        )
        reconcile_product_from_logs(product, dry_run=False)
        product.refresh_from_db()
        initial.refresh_from_db()
        real.refresh_from_db()
        phantom.refresh_from_db()
        assert product.quantity == Decimal('36')
        assert real.quantity == Decimal('5')
        assert real.is_active is True
        assert initial.quantity == Decimal('31')
        assert phantom.is_active is False


@pytest.mark.django_db
class TestReplayEdgeCases:
    def test_no_logs_returns_current_quantity(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('8'))
        assert replay_quantity_from_logs(product) == Decimal('8')

    def test_sold_with_positive_change_still_decrements(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('10'))
        ProductInventoryLog.objects.create(
            product=product,
            log_type='sold',
            quantity_change=Decimal('4'),
            previous_quantity=Decimal('10'),
            new_quantity=Decimal('6'),
            reason='unsigned sold row',
        )
        assert replay_quantity_from_logs(product) == Decimal('6')

    def test_returned_adds_back(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('3'))
        _write_logs(product, [
            ('sold', Decimal('-5'), Decimal('10'), Decimal('5'), None),
            ('returned', Decimal('2'), Decimal('5'), Decimal('7'), None),
        ])
        assert replay_quantity_from_logs(product) == Decimal('7')

    def test_damaged_and_expired_subtract(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('0'))
        _write_logs(product, [
            ('added', Decimal('10'), Decimal('0'), Decimal('10'), None),
            ('damaged', Decimal('3'), Decimal('10'), Decimal('7'), None),
            ('expired', Decimal('1'), Decimal('7'), Decimal('6'), None),
        ])
        assert replay_quantity_from_logs(product) == Decimal('6')

    def test_fractional_quantities(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('1.250'))
        _write_logs(product, [
            ('added', Decimal('1.500'), Decimal('0'), Decimal('1.500'), None),
            ('sold', Decimal('-0.250'), Decimal('1.500'), Decimal('1.250'), None),
        ])
        assert replay_quantity_from_logs(product) == Decimal('1.250')

    def test_unknown_log_type_uses_signed_change(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('9'))
        ProductInventoryLog.objects.create(
            product=product,
            log_type='added',
            quantity_change=Decimal('9'),
            previous_quantity=Decimal('0'),
            new_quantity=Decimal('9'),
            reason='seed',
        )
        ProductInventoryLog.objects.create(
            product=product,
            log_type='added',
            quantity_change=Decimal('-2'),
            previous_quantity=Decimal('9'),
            new_quantity=Decimal('7'),
            reason='odd signed added row',
        )
        # 'added' always applies abs(change), so this becomes +2 (documented)
        assert replay_quantity_from_logs(product) == Decimal('11')


@pytest.mark.django_db
class TestStockHelpers:
    def test_increase_without_batches_raises(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name='No batches',
            category=category,
            brand=brand,
            price=Decimal('1.00'),
            has_batches=True,
            track_inventory=True,
            quantity=Decimal('0'),
        )
        with pytest.raises(ValueError):
            apply_stock_increase(product, Decimal('5'))

    def test_decrease_without_allow_negative_raises(self, retailer, category, brand):
        product, initial = _batched_product(retailer, category, brand, quantity=Decimal('2'))
        with pytest.raises(ValueError):
            apply_stock_decrease(product, Decimal('5'), batch=initial, allow_negative=False)

    def test_decrease_allow_negative_goes_below_zero(self, retailer, category, brand):
        product, initial = _batched_product(retailer, category, brand, quantity=Decimal('2'))
        apply_stock_decrease(product, Decimal('5'), batch=initial, allow_negative=True)
        product.refresh_from_db()
        initial.refresh_from_db()
        assert product.quantity == Decimal('-3')
        assert initial.quantity == Decimal('-3')


@pytest.mark.django_db
class TestPOSLedgerRegression:
    def test_pos_without_batch_id_logs_product_balance(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('10'))
        product.sync_inventory_from_batches()
        response = api_client.post(
            reverse('create_pos_order'),
            {
                'subtotal': 10.0,
                'total_amount': 10.0,
                'items': [
                    {
                        'product_id': product.id,
                        'quantity': 2,
                        'unit_price': 5.0,
                    }
                ],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        log = ProductInventoryLog.objects.filter(product=product, log_type='sold').last()
        assert log.previous_quantity == Decimal('10')
        assert log.new_quantity == Decimal('8')
        product.refresh_from_db()
        assert product.quantity == Decimal('8')

    def test_pos_rejects_wrong_price(self, api_client, retailer_user, product):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.post(
            reverse('create_pos_order'),
            {
                'subtotal': 1.0,
                'total_amount': 1.0,
                'items': [
                    {
                        'product_id': product.id,
                        'quantity': 1,
                        'unit_price': 1.0,
                    }
                ],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestPurchaseNegativeAndUpdate:
    def test_purchase_on_untracked_product_does_not_change_qty(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name='Untracked',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            track_inventory=False,
            quantity=Decimal('3'),
        )
        supplier = Supplier.objects.create(retailer=retailer, company_name='KAN75 U')
        request = MagicMock()
        request.user = retailer.user
        serializer = PurchaseInvoiceSerializer(
            data={
                'supplier': supplier.id,
                'invoice_number': 'KAN75-UNTRACKED',
                'invoice_date': '2026-08-14',
                'total_amount': '10.00',
                'paid_amount': '0.00',
                'payment_status': 'UNPAID',
                'items': [
                    {
                        'product': product.id,
                        'quantity': 10,
                        'purchase_price': '1.00',
                        'total': '10.00',
                    }
                ],
            },
            context={'request': request, 'retailer': retailer},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save(retailer=retailer)
        product.refresh_from_db()
        assert product.quantity == Decimal('3')

    def test_purchase_delete_reverses_batch_stock(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product, initial = _batched_product(retailer, category, brand, quantity=Decimal('2'))
        supplier = Supplier.objects.create(retailer=retailer, company_name='KAN75 Del')
        request = MagicMock()
        request.user = retailer_user
        serializer = PurchaseInvoiceSerializer(
            data={
                'supplier': supplier.id,
                'invoice_number': 'KAN75-DEL',
                'invoice_date': '2026-08-14',
                'total_amount': '50.00',
                'paid_amount': '0.00',
                'payment_status': 'UNPAID',
                'items': [
                    {
                        'product': product.id,
                        'quantity': 10,
                        'purchase_price': '5.00',
                        'total': '50.00',
                    }
                ],
            },
            context={'request': request, 'retailer': retailer},
        )
        assert serializer.is_valid(), serializer.errors
        invoice = serializer.save(retailer=retailer)
        product.refresh_from_db()
        assert product.quantity == Decimal('12')

        response = api_client.delete(reverse('erp-purchase-invoice-detail', args=[invoice.id]))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        product.refresh_from_db()
        initial.refresh_from_db()
        assert product.quantity == Decimal('2')
        assert initial.quantity == Decimal('2')


@pytest.mark.django_db
class TestBulkUpdateAndLinkBarcode:
    def test_bulk_update_multi_batch_applies_delta_not_overwrite(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product, initial = _batched_product(retailer, category, brand, quantity=Decimal('9'))
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='B2',
            price=Decimal('5.00'),
            quantity=Decimal('5'),
            is_active=True,
        )
        product.sync_inventory_from_batches()
        assert product.quantity == Decimal('14')

        response = api_client.patch(
            reverse('bulk_update_products'),
            {'items': [{'id': product.id, 'quantity': 20}]},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        initial.refresh_from_db()
        assert product.quantity == Decimal('20')
        batch_sum = sum(b.quantity for b in product.batches.filter(is_active=True))
        assert batch_sum == product.quantity

    def test_bulk_update_rejects_negative_quantity(
        self, api_client, retailer_user, product
    ):
        api_client.force_authenticate(user=retailer_user)
        old = product.quantity
        response = api_client.patch(
            reverse('bulk_update_products'),
            {'items': [{'id': product.id, 'quantity': -3}]},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.quantity == old

    def test_link_barcode_does_not_drop_existing_stock(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product = Product.objects.create(
            retailer=retailer,
            name='Link stock',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            barcode='OLD-BC',
            quantity=Decimal('60'),
            track_inventory=True,
            is_active=True,
            is_available=True,
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='INITIAL-STOCK',
            barcode='OLD-BC',
            price=Decimal('5.00'),
            quantity=Decimal('60'),
            is_active=True,
        )
        response = api_client.patch(
            reverse('update_product', args=[product.id]),
            {'link_barcode': 'NEW-BC', 'price': 5.00},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        initial = product.batches.get(batch_number='INITIAL-STOCK')
        new_batch = product.batches.get(barcode='NEW-BC')
        assert product.quantity == Decimal('60')
        assert initial.quantity == Decimal('60')
        assert new_batch.quantity == Decimal('0')
        assert product.quantity == sum(
            b.quantity for b in product.batches.filter(is_active=True)
        )


@pytest.mark.django_db
class TestReconcileCommandQA:
    def test_requires_selector(self, capsys):
        call_command('reconcile_inventory_from_logs')
        captured = capsys.readouterr()
        assert 'Specify --product-id' in captured.err

    def test_apply_writes_replayed_qty(self, retailer, category, brand):
        product, initial, phantom = TestProduct111ProductionReplica()._seed(
            retailer, category, brand
        )
        call_command(
            'reconcile_inventory_from_logs',
            f'--product-id={product.id}',
            '--apply',
        )
        product.refresh_from_db()
        initial.refresh_from_db()
        phantom.refresh_from_db()
        assert product.quantity == Decimal('36')
        assert initial.quantity == Decimal('36')
        assert phantom.is_active is False

    def test_drifted_only_skips_in_sync_products(self, retailer, category, brand, capsys):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('4'))
        call_command('reconcile_inventory_from_logs', '--drifted-only')
        captured = capsys.readouterr()
        assert str(product.id) not in captured.out or 'No matching products' in captured.out

    def test_missing_product_warns(self, capsys):
        call_command('reconcile_inventory_from_logs', '--product-id=999999')
        captured = capsys.readouterr()
        assert 'No matching products' in captured.out

    def test_apply_drifted_only_requires_confirm(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('4'))
        product.quantity = Decimal('9')
        product.save(update_fields=['quantity'])
        with pytest.raises(CommandError, match='confirm-all-drifted'):
            call_command('reconcile_inventory_from_logs', '--drifted-only', '--apply')
        product.refresh_from_db()
        assert product.quantity == Decimal('9')

    def test_apply_product_id_does_not_need_confirm(self, retailer, category, brand):
        product, initial, phantom = TestProduct111ProductionReplica()._seed(
            retailer, category, brand
        )
        call_command(
            'reconcile_inventory_from_logs',
            f'--product-id={product.id}',
            '--apply',
        )
        product.refresh_from_db()
        assert product.quantity == Decimal('36')


@pytest.mark.django_db
class TestReconcileIdempotencyAndReplayBase:
    def test_apply_twice_keeps_replayed_quantity(self, retailer, category, brand):
        product, initial, phantom = TestProduct111ProductionReplica()._seed(
            retailer, category, brand
        )
        reconcile_product_from_logs(product, dry_run=False)
        first_repair_count = ProductInventoryLog.objects.filter(
            product=product, reason__contains='KAN-75'
        ).count()
        reconcile_product_from_logs(product, dry_run=False)
        product.refresh_from_db()
        initial.refresh_from_db()
        assert product.quantity == Decimal('36')
        assert initial.quantity == Decimal('36')
        assert replay_quantity_from_logs(product) == Decimal('36')
        assert ProductInventoryLog.objects.filter(
            product=product, reason__contains='KAN-75'
        ).count() == first_repair_count

    def test_zero_delta_apply_does_not_write_repair_log(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('8'))
        ProductInventoryLog.objects.create(
            product=product,
            log_type='added',
            quantity_change=Decimal('8'),
            previous_quantity=Decimal('0'),
            new_quantity=Decimal('8'),
            reason='seed',
        )
        result = reconcile_product_from_logs(product, dry_run=False)
        assert result['delta'] == Decimal('0')
        assert not ProductInventoryLog.objects.filter(
            product=product, reason__contains='KAN-75'
        ).exists()

    def test_replay_anchors_at_first_product_level_log(self, retailer, category, brand):
        product, initial = _batched_product(
            retailer, category, brand, quantity=Decimal('55')
        )
        phantom = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='',
            price=Decimal('5.00'),
            quantity=Decimal('0'),
            is_active=True,
        )
        _write_logs(product, [
            ('sold', Decimal('-4'), Decimal('0'), Decimal('-4'), 'phantom'),
            ('sold', Decimal('-1'), Decimal('56'), Decimal('55'), None),
        ], phantom=phantom)
        state = replay_inventory_state(product)
        assert replay_quantity_from_logs(product) == Decimal('55')
        assert state['base_trusted'] is True
        assert state['warning']

    def test_replay_warns_when_all_logs_are_batch_level(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('10'))
        phantom = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='',
            price=Decimal('5.00'),
            quantity=Decimal('0'),
            is_active=True,
        )
        _write_logs(product, [
            ('sold', Decimal('-4'), Decimal('0'), Decimal('-4'), 'phantom'),
        ], phantom=phantom)
        state = replay_inventory_state(product)
        assert state['base_trusted'] is False
        assert 'batch-level' in state['warning']
        assert state['quantity'] == Decimal('-4')

    def test_dry_run_does_not_row_lock(self, retailer, category, brand):
        product, _ = _batched_product(retailer, category, brand, quantity=Decimal('8'))
        with patch('products.inventory_service.Product.objects.select_for_update') as mock_sfu:
            result = reconcile_product_from_logs(product, dry_run=True)
        mock_sfu.assert_not_called()
        assert result['dry_run'] is True

    def test_apply_creates_initial_stock_when_barcode_taken(
        self, retailer, category, brand
    ):
        product = Product.objects.create(
            retailer=retailer,
            name='No initial',
            category=category,
            brand=brand,
            barcode='SHARED-BC',
            price=Decimal('5.00'),
            has_batches=True,
            track_inventory=True,
            quantity=Decimal('5'),
        )
        other = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='B-REAL',
            barcode='SHARED-BC',
            price=Decimal('5.00'),
            quantity=Decimal('5'),
            is_active=True,
        )
        ProductInventoryLog.objects.create(
            product=product,
            log_type='added',
            quantity_change=Decimal('10'),
            previous_quantity=Decimal('0'),
            new_quantity=Decimal('10'),
            reason='seed',
        )
        reconcile_product_from_logs(product, dry_run=False)
        initial = product.batches.get(batch_number='INITIAL-STOCK')
        other.refresh_from_db()
        product.refresh_from_db()
        assert other.barcode == 'SHARED-BC'
        assert initial.barcode in (None, '')
        assert product.quantity == Decimal('10')
        assert other.quantity == Decimal('5')
        assert initial.quantity == Decimal('5')


@pytest.mark.django_db
class TestReturnsLedger:
    def test_sales_return_logs_product_level_balance(self, retailer, category, brand):
        from returns.services import process_sales_return

        product, initial = _batched_product(
            retailer, category, brand, quantity=Decimal('10')
        )
        process_sales_return(
            retailer,
            None,
            [{
                'product': product,
                'batch': initial,
                'quantity': Decimal('2'),
                'refund_unit_price': Decimal('5.00'),
            }],
            'cash',
            'KAN75 return',
            retailer.user,
        )
        product.refresh_from_db()
        initial.refresh_from_db()
        log = ProductInventoryLog.objects.filter(product=product, log_type='returned').last()
        assert product.quantity == Decimal('12')
        assert initial.quantity == Decimal('12')
        assert log.previous_quantity == Decimal('10')
        assert log.new_quantity == Decimal('12')
        assert log.quantity_change == Decimal('2')

    def test_sales_return_failed_increase_raises(self, retailer, category, brand):
        from returns.services import process_sales_return

        product = Product.objects.create(
            retailer=retailer,
            name='No batch rows',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            has_batches=True,
            track_inventory=True,
            quantity=Decimal('0'),
        )
        with pytest.raises(ValueError):
            process_sales_return(
                retailer,
                None,
                [{
                    'product': product,
                    'quantity': Decimal('2'),
                    'refund_unit_price': Decimal('5.00'),
                }],
                'cash',
                'KAN75 fail',
                retailer.user,
            )

    def test_purchase_return_logs_product_level_balance(
        self, retailer, category, brand
    ):
        from returns.services import process_purchase_return

        product, initial = _batched_product(
            retailer, category, brand, quantity=Decimal('10')
        )
        supplier = Supplier.objects.create(retailer=retailer, company_name='KAN75 PR')
        process_purchase_return(
            retailer,
            supplier,
            None,
            [{
                'product': product,
                'batch': initial,
                'quantity': Decimal('3'),
                'purchase_price': Decimal('4.00'),
            }],
            'KAN75 purchase return',
            retailer.user,
        )
        product.refresh_from_db()
        initial.refresh_from_db()
        log = ProductInventoryLog.objects.filter(product=product, log_type='removed').last()
        assert product.quantity == Decimal('7')
        assert initial.quantity == Decimal('7')
        assert log.previous_quantity == Decimal('10')
        assert log.new_quantity == Decimal('7')
        assert log.quantity_change == Decimal('-3')


@pytest.mark.django_db
class TestBulkUpdateFractionalAndProductUpdateLog:
    def test_bulk_update_preserves_fractional_quantity(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product = Product.objects.create(
            retailer=retailer,
            name='Fractional',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            track_inventory=True,
            has_batches=False,
            quantity=Decimal('1.500'),
        )
        response = api_client.patch(
            reverse('bulk_update_products'),
            {'items': [{'id': product.id, 'quantity': '2.250'}]},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.quantity == Decimal('2.250')
        log = ProductInventoryLog.objects.filter(product=product, reason='Bulk update').last()
        assert log.quantity_change == Decimal('0.750')
        assert log.previous_quantity == Decimal('1.500')
        assert log.new_quantity == Decimal('2.250')

    def test_update_product_quantity_logs_via_helper(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product = Product.objects.create(
            retailer=retailer,
            name='Update log',
            category=category,
            brand=brand,
            price=Decimal('5.00'),
            track_inventory=True,
            quantity=Decimal('10'),
            is_active=True,
            is_available=True,
        )
        response = api_client.patch(
            reverse('update_product', args=[product.id]),
            {'quantity': 7, 'price': 5.00},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        log = ProductInventoryLog.objects.filter(product=product, reason='Product update').last()
        assert log is not None
        assert log.previous_quantity == Decimal('10')
        assert log.new_quantity == Decimal('7')
        assert log.quantity_change == Decimal('3')


@pytest.mark.django_db
class TestToothbrushScreenshotLedgerJump:
    """
    ENSHINE ULTRA SOFT TOOTHBRUSH 1N (shop screenshot):

    Purchase Updated +96 → New Balance 98, then POS sold 1 and the
    audit trail jumped to -1 (then -2, -3). Purchase had written the
    header only; POS deducted an empty barcode batch and
    sync_inventory_from_batches snapped current stock to the batch sum.
    """

    def _seed(self, retailer, category, brand):
        product, initial = _batched_product(
            retailer,
            category,
            brand,
            name='ENSHINE ULRA SOFT TOOTHBRUSH 1N',
            quantity=Decimal('2'),
        )
        phantom = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='',
            price=Decimal('5.00'),
            quantity=Decimal('0'),
            is_active=True,
        )
        product.sync_inventory_from_batches()
        return product, initial, phantom

    def test_purchase_then_pos_from_empty_batch_stays_at_97(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product, initial, phantom = self._seed(retailer, category, brand)
        supplier = Supplier.objects.create(retailer=retailer, company_name='L-2464 Supplier')
        request = MagicMock()
        request.user = retailer_user

        serializer = PurchaseInvoiceSerializer(
            data={
                'supplier': supplier.id,
                'invoice_number': 'L-2464',
                'invoice_date': '2026-08-31',
                'total_amount': '96.00',
                'paid_amount': '0.00',
                'payment_status': 'UNPAID',
                'items': [
                    {
                        'product': product.id,
                        'quantity': 96,
                        'purchase_price': '1.00',
                        'total': '96.00',
                    }
                ],
            },
            context={'request': request, 'retailer': retailer},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save(retailer=retailer)

        product.refresh_from_db()
        batch_sum = sum(b.quantity for b in product.batches.filter(is_active=True))
        assert product.quantity == Decimal('98')
        assert batch_sum == Decimal('98')

        added = ProductInventoryLog.objects.filter(product=product, log_type='added').last()
        assert added.new_quantity == Decimal('98')
        assert added.quantity_change == Decimal('96')

        response = api_client.post(
            reverse('create_pos_order'),
            {
                'subtotal': 5.0,
                'total_amount': 5.0,
                'items': [
                    {
                        'product_id': product.id,
                        'batch_id': phantom.id,
                        'quantity': 1,
                        'unit_price': 5.0,
                    }
                ],
            },
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED

        product.refresh_from_db()
        sold = ProductInventoryLog.objects.filter(product=product, log_type='sold').last()
        assert sold.previous_quantity == Decimal('98')
        assert sold.new_quantity == Decimal('97')
        assert sold.quantity_change == Decimal('-1')
        assert product.quantity == Decimal('97')
        assert product.quantity != Decimal('-1')

        for _ in range(2):
            response = api_client.post(
                reverse('create_pos_order'),
                {
                    'subtotal': 5.0,
                    'total_amount': 5.0,
                    'items': [
                        {
                            'product_id': product.id,
                            'batch_id': phantom.id,
                            'quantity': 1,
                            'unit_price': 5.0,
                        }
                    ],
                },
                format='json',
            )
            assert response.status_code == status.HTTP_201_CREATED

        product.refresh_from_db()
        assert product.quantity == Decimal('95')
        sold_balances = list(
            ProductInventoryLog.objects.filter(product=product, log_type='sold')
            .order_by('id')
            .values_list('new_quantity', flat=True)
        )
        assert sold_balances == [Decimal('97'), Decimal('96'), Decimal('95')]

    def test_ledger_api_replays_product_balances_for_legacy_batch_logs(
        self, api_client, retailer_user, retailer, category, brand
    ):
        api_client.force_authenticate(user=retailer_user)
        product, _initial, phantom = self._seed(retailer, category, brand)
        product.quantity = Decimal('-3')
        product.save(update_fields=['quantity'])

        ProductInventoryLog.objects.create(
            product=product,
            log_type='added',
            quantity_change=Decimal('96'),
            previous_quantity=Decimal('2'),
            new_quantity=Decimal('98'),
            reason='Purchase Updated: Invoice #L-2464',
        )
        for prev, new in [
            (Decimal('0'), Decimal('-1')),
            (Decimal('-1'), Decimal('-2')),
            (Decimal('-2'), Decimal('-3')),
        ]:
            ProductInventoryLog.objects.create(
                product=product,
                batch=phantom,
                log_type='sold',
                quantity_change=Decimal('-1'),
                previous_quantity=prev,
                new_quantity=new,
                reason='POS Sale: Order #ORD-legacy',
            )

        overlay = product_level_log_balances(product)
        sold_ids = list(
            ProductInventoryLog.objects.filter(product=product, log_type='sold')
            .order_by('id')
            .values_list('id', flat=True)
        )
        assert overlay[sold_ids[0]] == (Decimal('98'), Decimal('97'))
        assert overlay[sold_ids[1]] == (Decimal('97'), Decimal('96'))
        assert overlay[sold_ids[2]] == (Decimal('96'), Decimal('95'))

        response = api_client.get(
            reverse('get_inventory_ledger'), {'product_id': product.id}
        )
        assert response.status_code == status.HTTP_200_OK
        sold_rows = [row for row in response.data if row['log_type'] == 'sold']
        sold_rows = sorted(sold_rows, key=lambda row: row['id'])
        assert [Decimal(str(row['new_quantity'])) for row in sold_rows] == [
            Decimal('97'),
            Decimal('96'),
            Decimal('95'),
        ]
        assert Decimal('-1') not in [Decimal(str(row['new_quantity'])) for row in sold_rows]
