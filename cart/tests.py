from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from authentication.models import User
from cart.models import CartHistory
from cart.serializers import AddToCartSerializer
from products.models import Product
from retailers.models import RetailerProfile


class AddToCartSerializerTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='cart-customer',
            password='test-pass',
            user_type='customer'
        )
        retailer_user = User.objects.create_user(
            username='cart-retailer',
            password='test-pass',
            user_type='retailer'
        )
        self.retailer = RetailerProfile.objects.create(
            user=retailer_user,
            shop_name='Cart Test Store',
            address_line1='123 Test Street',
            city='Test City',
            state='Test State',
            pincode='123456',
            offers_delivery=True,
            offers_pickup=True
        )
        self.product = Product.objects.create(
            retailer=self.retailer,
            name='Milk',
            price=Decimal('55.00'),
            quantity=50,
            is_active=True,
            is_available=True,
            track_inventory=True
        )

    def test_reuses_single_product_lookup_and_keeps_payload(self):
        serializer = AddToCartSerializer(
            data={'product_id': self.product.id, 'quantity': 2},
            context={'customer': self.customer}
        )

        with CaptureQueriesContext(connection) as queries:
            self.assertTrue(serializer.is_valid(), serializer.errors)
            cart_item = serializer.save()

        product_id_lookups = [
            q['sql'] for q in queries.captured_queries
            if 'FROM "products_product"' in q['sql']
            and f'"products_product"."id" = {self.product.id}' in q['sql']
        ]
        self.assertEqual(len(product_id_lookups), 1)

        self.assertEqual(
            serializer.validated_data,
            {'product_id': self.product.id, 'quantity': 2}
        )
        self.assertEqual(cart_item.product_id, self.product.id)
        self.assertEqual(cart_item.quantity, 2)
        self.assertEqual(cart_item.unit_price, Decimal('55.00'))
        self.assertEqual(CartHistory.objects.filter(action='add').count(), 1)
