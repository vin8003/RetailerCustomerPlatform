import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from django.urls import reverse
from rest_framework import status

from orders.models import OrderItem, PaymentTransaction
from orders.serializers import (
    OrderDetailSerializer,
    OrderListSerializer,
    OrderModificationSerializer,
)
from products.models import ProductInventoryLog


@pytest.mark.django_db
class TestOrderModificationInventoryLogs:
    """Regression: qty-only / add-item modify must not UnboundLocalError ProductInventoryLog."""

    def test_quantity_increase_creates_inventory_log(
        self, retailer_user, order, product
    ):
        item = order.items.get()
        request = MagicMock(user=retailer_user)
        serializer = OrderModificationSerializer(
            order,
            data={'items': [{'id': item.id, 'quantity': 3}]},
            context={'user': retailer_user, 'request': request},
        )

        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()
        item.refresh_from_db()
        product.refresh_from_db()

        assert item.quantity == Decimal('3')
        assert product.quantity == Decimal('49')  # 50 stock fixture minus +1 sold
        assert updated.status == 'waiting_for_customer_approval'
        assert ProductInventoryLog.objects.filter(
            product=product,
            log_type='sold',
            reason__startswith='Order Modification:',
        ).exists()

    def test_add_product_creates_inventory_log(
        self, retailer_user, order, product2
    ):
        existing = order.items.get()
        request = MagicMock(user=retailer_user)
        serializer = OrderModificationSerializer(
            order,
            data={
                'items': [
                    {
                        'id': existing.id,
                        'quantity': existing.quantity,
                    },
                    {'product_id': product2.id, 'quantity': 1},
                ]
            },
            context={'user': retailer_user, 'request': request},
        )

        assert serializer.is_valid(), serializer.errors
        serializer.save()
        product2.refresh_from_db()
        added = OrderItem.objects.get(order=order, product=product2)

        assert added.gst_rate is not None
        assert added.tax_type == 'GST'
        assert product2.quantity == Decimal('19')
        assert ProductInventoryLog.objects.filter(
            product=product2,
            log_type='sold',
            reason__startswith='Order Item Added:',
        ).exists()

    def test_modify_order_api_quantity_change(
        self, api_client, retailer_user, order
    ):
        item = order.items.get()
        api_client.force_authenticate(user=retailer_user)
        response = api_client.post(
            reverse('modify_order', args=[order.id]),
            {
                'items': [
                    {
                        'id': item.id,
                        'quantity': 1,
                    }
                ]
            },
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert 'ProductInventoryLog' not in str(response.data)
        item.refresh_from_db()
        assert item.quantity == Decimal('1')


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
