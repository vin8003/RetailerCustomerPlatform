from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from authentication.models import User
from cart.models import Cart, CartItem
from orders.models import Order, OrderItem
from orders.serializers import OrderCreateSerializer
from products.models import Product
from retailers.models import RetailerProfile


class OrderCreateSerializerTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='order-customer',
            password='test-pass',
            user_type='customer'
        )
        retailer_user = User.objects.create_user(
            username='order-retailer',
            password='test-pass',
            user_type='retailer'
        )
        self.retailer = RetailerProfile.objects.create(
            user=retailer_user,
            shop_name='Order Test Store',
            address_line1='123 Test Street',
            city='Test City',
            state='Test State',
            pincode='123456',
            offers_delivery=False,
            offers_pickup=True,
            accepts_cod=True,
            accepts_upi=True,
            minimum_order_amount=Decimal('10.00')
        )
        self.product = Product.objects.create(
            retailer=self.retailer,
            name='Bread',
            price=Decimal('40.00'),
            quantity=20,
            is_active=True,
            is_available=True,
            track_inventory=True
        )
        self.cart = Cart.objects.create(customer=self.customer, retailer=self.retailer)
        CartItem.objects.create(
            cart=self.cart,
            product=self.product,
            quantity=2,
            unit_price=self.product.price
        )

    def test_reuses_retailer_and_cart_and_keeps_output(self):
        serializer = OrderCreateSerializer(
            data={
                'retailer_id': self.retailer.id,
                'delivery_mode': 'pickup',
                'payment_mode': 'cash_pickup',
                'special_instructions': 'No plastic bag',
                'use_reward_points': False,
            },
            context={'customer': self.customer}
        )

        with CaptureQueriesContext(connection) as queries:
            self.assertTrue(serializer.is_valid(), serializer.errors)
            order = serializer.save()

        retailer_id_lookups = [
            q['sql'] for q in queries.captured_queries
            if 'FROM "retailer_profile"' in q['sql']
            and f'"retailer_profile"."id" = {self.retailer.id}' in q['sql']
        ]
        cart_lookups = [
            q['sql'] for q in queries.captured_queries
            if 'FROM "cart"' in q['sql']
            and f'"cart"."customer_id" = {self.customer.id}' in q['sql']
            and f'"cart"."retailer_id" = {self.retailer.id}' in q['sql']
        ]

        self.assertEqual(len(retailer_id_lookups), 1)
        self.assertEqual(len(cart_lookups), 1)
        self.assertEqual(serializer.validated_data['retailer_id'], self.retailer.id)
        self.assertEqual(serializer.validated_data['payment_mode'], 'cash_pickup')

        created_order = Order.objects.get(id=order.id)
        self.assertEqual(created_order.retailer_id, self.retailer.id)
        self.assertEqual(created_order.customer_id, self.customer.id)
        self.assertEqual(created_order.special_instructions, 'No plastic bag')
        self.assertEqual(created_order.total_amount, Decimal('80.00'))
        self.assertEqual(OrderItem.objects.filter(order=created_order).count(), 1)
