from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from authentication.models import User
from customers.models import CustomerAddress, CustomerNotification, CustomerWishlist
from orders.models import Order
from products.models import Product
from retailers.models import RetailerProfile


class CustomerDashboardQueryCountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse('get_customer_dashboard')

        self.customer = User.objects.create_user(
            username='dashboard-customer',
            password='testpass123',
            user_type='customer'
        )
        self.client.force_authenticate(user=self.customer)

        self.retailer_user = User.objects.create_user(
            username='retailer-user',
            password='testpass123',
            user_type='retailer'
        )
        self.retailer = RetailerProfile.objects.create(
            user=self.retailer_user,
            shop_name='Test Retailer',
            address_line1='123 Retail St',
            city='Test City',
            state='Test State',
            pincode='123456'
        )

        self.product = Product.objects.create(
            retailer=self.retailer,
            name='Wishlist Product',
            price=Decimal('25.00')
        )
        CustomerWishlist.objects.create(customer=self.customer, product=self.product)

        CustomerAddress.objects.create(
            customer=self.customer,
            title='Home',
            address_line1='456 Customer Ave',
            city='Test City',
            state='Test State',
            pincode='654321',
            is_active=True
        )
        CustomerNotification.objects.create(
            customer=self.customer,
            notification_type='system',
            title='Unread Notification',
            message='Important update',
            is_read=False
        )

        self._create_order('pending', Decimal('50.00'))
        self._create_order('confirmed', Decimal('75.00'))
        self._create_order('delivered', Decimal('100.00'))
        self._create_order('cancelled', Decimal('20.00'))

    def _create_order(self, status_value, total_amount):
        return Order.objects.create(
            customer=self.customer,
            retailer=self.retailer,
            delivery_mode='delivery',
            payment_mode='cash',
            status=status_value,
            subtotal=total_amount,
            total_amount=total_amount
        )

    def test_get_customer_dashboard_query_count(self):
        with self.assertNumQueries(6):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_orders'], 4)
        self.assertEqual(response.data['pending_orders'], 2)
        self.assertEqual(response.data['delivered_orders'], 1)
        self.assertEqual(response.data['cancelled_orders'], 1)
        self.assertEqual(response.data['total_spent'], '100.00')
        self.assertEqual(response.data['wishlist_count'], 1)
        self.assertEqual(response.data['addresses_count'], 1)
        self.assertEqual(response.data['unread_notifications'], 1)
        self.assertIsInstance(response.data['recent_orders'], list)
        self.assertIsInstance(response.data['favorite_retailers'], list)
