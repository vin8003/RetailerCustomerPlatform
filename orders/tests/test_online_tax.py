from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from cart.models import Cart, CartItem
from offers.models import Offer, OfferTarget
from orders.models import Order, OrderItem
from orders.serializers import OrderCreateSerializer, OrderModificationSerializer


@pytest.mark.django_db
class TestOnlineOrderTax:
    def test_create_snapshots_tax_after_offer(self, customer, retailer, product):
        product.price = Decimal('118.00')
        product.gst_rate = Decimal('18.00')
        product.hsn_code = '21069099'
        product.save(update_fields=['price', 'gst_rate', 'hsn_code'])
        offer = Offer.objects.create(
            retailer=retailer,
            name='Online 10% Off',
            offer_type='percentage',
            value=Decimal('10.00'),
            applicable_on='mobile',
            is_active=True,
        )
        OfferTarget.objects.create(
            offer=offer,
            target_type='product',
            product=product,
        )
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
            unit_price=product.price,
        )

        serializer = OrderCreateSerializer(
            data={
                'retailer_id': retailer.id,
                'delivery_mode': 'pickup',
                'payment_mode': 'cash_pickup',
            },
            context={'customer': customer},
        )

        assert serializer.is_valid(), serializer.errors
        order = serializer.save()
        item = order.items.get()
        assert order.total_amount == Decimal('106.20')
        assert order.taxable_amount == Decimal('90.00')
        assert order.tax_amount == Decimal('16.20')
        assert item.total_price == Decimal('106.20')
        assert item.hsn_code == '21069099'
        assert item.gst_rate == Decimal('18.00')
        assert item.taxable_value == Decimal('90.00')
        assert item.tax_amount == Decimal('16.20')
        assert item.tax_type == 'GST'

    def test_modification_resnapshots_line_and_header_tax(
        self, customer, retailer, retailer_user, product
    ):
        product.price = Decimal('118.00')
        product.gst_rate = Decimal('18.00')
        product.hsn_code = '21069099'
        product.save(update_fields=['price', 'gst_rate', 'hsn_code'])
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_mode='pickup',
            payment_mode='cash_pickup',
            subtotal=Decimal('118.00'),
            delivery_fee=Decimal('0.00'),
            discount_amount=Decimal('0.00'),
            discount_from_points=Decimal('10.00'),
            total_amount=Decimal('108.00'),
            source='app',
        )
        item = OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=1,
            unit_price=product.price,
            total_price=product.price,
        )
        request = MagicMock(user=retailer_user)
        serializer = OrderModificationSerializer(
            order,
            data={'items': [{'id': item.id, 'quantity': '2'}]},
            context={'user': retailer_user, 'request': request},
        )

        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()
        item.refresh_from_db()
        assert updated.total_amount == Decimal('226.00')
        assert updated.taxable_amount == Decimal('200.00')
        assert updated.tax_amount == Decimal('36.00')
        assert item.hsn_code == '21069099'
        assert item.gst_rate == Decimal('18.00')
        assert item.taxable_value == Decimal('200.00')
        assert item.tax_amount == Decimal('36.00')
        assert item.tax_type == 'GST'
