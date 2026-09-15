from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from cart.models import Cart, CartItem
from offers.models import Offer, OfferTarget
from orders.models import Order, OrderItem
from orders.serializers import OrderCreateSerializer, OrderModificationSerializer


def _order_item(order, product, unit_price, *, quantity=1, gst_rate=Decimal('18.00'),
                hsn_code='21069099'):
    """Create an order line already carrying its sale-time tax snapshot."""
    total_price = unit_price * quantity
    taxable = (total_price / (1 + gst_rate / 100)).quantize(Decimal('0.01'))
    return OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        product_price=product.price,
        product_unit=product.unit,
        quantity=quantity,
        unit_price=unit_price,
        total_price=total_price,
        hsn_code=hsn_code,
        gst_rate=gst_rate,
        taxable_value=taxable,
        tax_amount=total_price - taxable,
        tax_type='GST',
    )


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
            hsn_code='21069099',
            gst_rate=Decimal('18.00'),
            taxable_value=Decimal('100.00'),
            tax_amount=Decimal('18.00'),
            tax_type='GST',
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

    def test_modification_keeps_stored_rate_when_product_rate_changed(
        self, customer, retailer, retailer_user, product, product2
    ):
        """An order sold at 18% must not re-rate when the product master changes."""
        for prod in (product, product2):
            prod.price = Decimal('118.00')
            prod.gst_rate = Decimal('18.00')
            prod.hsn_code = '21069099'
            prod.save(update_fields=['price', 'gst_rate', 'hsn_code'])
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_mode='pickup',
            payment_mode='cash_pickup',
            subtotal=Decimal('236.00'),
            delivery_fee=Decimal('0.00'),
            discount_amount=Decimal('0.00'),
            total_amount=Decimal('236.00'),
            taxable_amount=Decimal('200.00'),
            tax_amount=Decimal('36.00'),
            source='app',
        )
        kept_item = _order_item(order, product, Decimal('118.00'))
        removed_item = _order_item(order, product2, Decimal('118.00'))

        # Retailer corrects the product master after the sale.
        for prod in (product, product2):
            prod.gst_rate = Decimal('5.00')
            prod.hsn_code = '19059090'
            prod.save(update_fields=['gst_rate', 'hsn_code'])

        request = MagicMock(user=retailer_user)
        serializer = OrderModificationSerializer(
            order,
            data={'items': [{'id': removed_item.id, 'quantity': '0'}]},
            context={'user': retailer_user, 'request': request},
        )

        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()
        kept_item.refresh_from_db()

        assert not OrderItem.objects.filter(pk=removed_item.pk).exists()
        assert kept_item.gst_rate == Decimal('18.00')
        assert kept_item.hsn_code == '21069099'
        assert kept_item.tax_type == 'GST'
        assert kept_item.taxable_value == Decimal('100.00')
        assert kept_item.tax_amount == Decimal('18.00')
        assert updated.taxable_amount == Decimal('100.00')
        assert updated.tax_amount == Decimal('18.00')
        assert updated.total_amount == Decimal('118.00')

    def test_modification_allocates_order_discount_before_tax_split(
        self, customer, retailer, retailer_user, product, product2
    ):
        for prod in (product, product2):
            prod.price = Decimal('118.00')
            prod.gst_rate = Decimal('18.00')
            prod.hsn_code = '21069099'
            prod.save(update_fields=['price', 'gst_rate', 'hsn_code'])
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_mode='pickup',
            payment_mode='cash_pickup',
            subtotal=Decimal('236.00'),
            delivery_fee=Decimal('0.00'),
            discount_amount=Decimal('0.00'),
            total_amount=Decimal('236.00'),
            taxable_amount=Decimal('200.00'),
            tax_amount=Decimal('36.00'),
            source='app',
        )
        first_item = _order_item(order, product, Decimal('118.00'))
        second_item = _order_item(order, product2, Decimal('118.00'))

        request = MagicMock(user=retailer_user)
        serializer = OrderModificationSerializer(
            order,
            data={
                'items': [{'id': first_item.id, 'quantity': '1'}],
                'discount_amount': '20.00',
            },
            context={'user': retailer_user, 'request': request},
        )

        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()
        first_item.refresh_from_db()
        second_item.refresh_from_db()

        # 20.00 spreads 10.00/10.00 across the two equal lines, then each
        # 108.00 inclusive line splits into 91.53 + 16.47.
        assert first_item.taxable_value == Decimal('91.53')
        assert first_item.tax_amount == Decimal('16.47')
        assert second_item.taxable_value == Decimal('91.53')
        assert second_item.tax_amount == Decimal('16.47')
        assert updated.discount_amount == Decimal('20.00')
        assert updated.taxable_amount == Decimal('183.06')
        assert updated.tax_amount == Decimal('32.94')
        assert updated.total_amount == Decimal('216.00')
        # Header break-up reconciles with the post-discount inclusive lines.
        assert updated.taxable_amount + updated.tax_amount == updated.total_amount

    def test_zero_rate_order_matches_pre_gst_totals(self, customer, retailer, product):
        product.price = Decimal('118.00')
        product.gst_rate = Decimal('0.00')
        product.hsn_code = ''
        product.save(update_fields=['price', 'gst_rate', 'hsn_code'])
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=2,
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

        assert order.subtotal == Decimal('236.00')
        assert order.total_amount == Decimal('236.00')
        assert order.tax_amount == Decimal('0.00')
        assert order.taxable_amount == Decimal('236.00')
        assert item.total_price == Decimal('236.00')
        assert item.gst_rate == Decimal('0.00')
        assert item.taxable_value == item.total_price
        assert item.tax_amount == Decimal('0.00')
