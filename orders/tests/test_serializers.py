import pytest
from decimal import Decimal

from orders.models import PaymentTransaction
from orders.serializers import OrderDetailSerializer, OrderListSerializer


@pytest.mark.django_db
class TestOrderPaymentSerializers:
    def test_schema_fields_unchanged_with_transaction_source(self, order):
        PaymentTransaction.objects.create(
            order=order,
            method='upi',
            amount=Decimal('200.00'),
            reference_id='TXN001',
            status='pending_verification',
        )

        data = OrderDetailSerializer(order).data
        assert data['payment_status'] == 'pending_verification'
        assert data['payment_reference_id'] == 'TXN001'
        assert Decimal(str(data['cash_amount'])) == Decimal('0.00')
        assert Decimal(str(data['upi_amount'])) == Decimal('200.00')

    def test_split_payment_totals_from_transactions(self, order):
        PaymentTransaction.objects.create(order=order, method='cash', amount=Decimal('50.00'), status='verified')
        PaymentTransaction.objects.create(order=order, method='card', amount=Decimal('150.00'), status='verified')

        data = OrderDetailSerializer(order).data
        assert Decimal(str(data['cash_amount'])) == Decimal('50.00')
        assert Decimal(str(data['card_amount'])) == Decimal('150.00')
        assert Decimal(str(data['upi_amount'])) == Decimal('0.00')

    def test_legacy_fallback_without_transactions(self, order):
        order.cash_amount = Decimal('80.00')
        order.upi_amount = Decimal('120.00')
        order.payment_status = 'verified'
        order.payment_reference_id = 'LEGACYREF'
        order.save()

        detail_data = OrderDetailSerializer(order).data
        list_data = OrderListSerializer(order).data

        assert detail_data['payment_status'] == 'verified'
        assert detail_data['payment_reference_id'] == 'LEGACYREF'
        assert Decimal(str(detail_data['cash_amount'])) == Decimal('80.00')
        assert Decimal(str(list_data['upi_amount'])) == Decimal('120.00')
