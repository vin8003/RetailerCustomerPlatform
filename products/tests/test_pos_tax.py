from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from orders.models import Order


@pytest.mark.django_db
class TestPOSTax:
    def test_pos_order_snapshots_inclusive_gst(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        retailer.gst_number = '27AAAAA0000A1Z5'
        retailer.save(update_fields=['gst_number'])
        product.price = Decimal('118.00')
        product.gst_rate = Decimal('18.00')
        product.hsn_code = '21069099'
        product.save(update_fields=['price', 'gst_rate', 'hsn_code'])

        response = api_client.post(
            reverse('create_pos_order'),
            {
                'items': [
                    {
                        'product_id': product.id,
                        'quantity': 1,
                        'unit_price': '118.00',
                    }
                ],
                'payment_mode': 'cash',
                'discount_amount': '0.00',
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        order = Order.objects.get(pk=response.data['order']['id'])
        item = order.items.get()
        assert order.taxable_amount == Decimal('100.00')
        assert order.tax_amount == Decimal('18.00')
        assert order.total_amount == Decimal('118.00')
        assert item.hsn_code == '21069099'
        assert item.gst_rate == Decimal('18.00')
        assert item.taxable_value == Decimal('100.00')
        assert item.tax_amount == Decimal('18.00')
        assert item.tax_type == 'GST'
        assert Decimal(response.data['order']['taxable_amount']) == Decimal('100.00')
        assert Decimal(response.data['order']['tax_amount']) == Decimal('18.00')
        assert response.data['order']['items'][0]['hsn_code'] == '21069099'

    def test_manual_discount_is_allocated_before_inclusive_tax(
        self, api_client, retailer_user, product
    ):
        api_client.force_authenticate(user=retailer_user)
        product.price = Decimal('118.00')
        product.gst_rate = Decimal('18.00')
        product.save(update_fields=['price', 'gst_rate'])

        response = api_client.post(
            reverse('create_pos_order'),
            {
                'items': [
                    {
                        'product_id': product.id,
                        'quantity': 1,
                        'unit_price': '118.00',
                    }
                ],
                'payment_mode': 'cash',
                'discount_amount': '18.00',
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        order = Order.objects.get(pk=response.data['order']['id'])
        item = order.items.get()
        assert order.total_amount == Decimal('100.00')
        assert order.taxable_amount == Decimal('84.75')
        assert order.tax_amount == Decimal('15.25')
        assert item.taxable_value == Decimal('84.75')
        assert item.tax_amount == Decimal('15.25')
