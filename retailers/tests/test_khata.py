from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from retailers.models import RetailerProfile, RetailerCustomerMapping, CustomerLedger
from products.models import Product
from decimal import Decimal
from django.urls import reverse

User = get_user_model()

class KhataSystemTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        # Create Retailer
        self.retailer_user = User.objects.create_user(
            username='retailer_test',
            password='password123',
            user_type='retailer'
        )
        self.retailer = RetailerProfile.objects.create(
            user=self.retailer_user,
            shop_name='Test Shop'
        )
        self.client.force_authenticate(user=self.retailer_user)
        
        # Create Customer
        self.customer_user = User.objects.create_user(
            username='9988776655',
            password='password123',
            user_type='customer',
            phone_number='9988776655'
        )
        
        # Create Product
        self.product = Product.objects.create(
            retailer=self.retailer,
            name='Test Product',
            price=Decimal('100.00'),
            quantity=100,
            track_inventory=True
        )

    def test_pos_split_payment_credit(self):
        """Test POS sale with cash + credit split"""
        url = '/api/products/erp/pos-checkout/'
        data = {
            'items': [
                {'product_id': self.product.id, 'quantity': 5, 'unit_price': 100}
            ],
            'subtotal': 500,
            'total_amount': 500,
            'customer_mobile': '9988776655',
            'payment_details': {
                'cash': 200,
                'credit': 300
            }
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify Mapping Balance
        mapping = RetailerCustomerMapping.objects.get(retailer=self.retailer, customer=self.customer_user)
        self.assertEqual(mapping.current_balance, Decimal('300.00'))
        
        # Verify Ledger Entry
        ledger = CustomerLedger.objects.filter(mapping=mapping).first()
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.transaction_type, 'SALE')
        self.assertEqual(ledger.amount, Decimal('300.00'))
        self.assertEqual(ledger.balance_after, Decimal('300.00'))

    def test_manual_payment_collection(self):
        """Test recording a manual payment from customer"""
        # First create a balance
        mapping = RetailerCustomerMapping.objects.create(
            retailer=self.retailer,
            customer=self.customer_user,
            current_balance=Decimal('500.00')
        )
        
        url = reverse('record_customer_payment')
        data = {
            'customer_id': self.customer_user.id,
            'amount': 200,
            'payment_mode': 'cash',
            'notes': 'Paid some udhaar'
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        mapping.refresh_from_db()
        self.assertEqual(mapping.current_balance, Decimal('300.00'))
        
        # Verify Ledger
        ledger = CustomerLedger.objects.filter(mapping=mapping, transaction_type='PAYMENT').first()
        self.assertEqual(ledger.amount, Decimal('200.00'))
        self.assertEqual(ledger.balance_after, Decimal('300.00'))

    def test_credit_limit_enforcement(self):
        """Test that credit limit is respected (warning/error logic if implemented)"""
        # Set a limit
        mapping = RetailerCustomerMapping.objects.create(
            retailer=self.retailer,
            customer=self.customer_user,
            credit_limit=Decimal('100.00'),
            current_balance=Decimal('50.00')
        )
        
        url = '/api/products/erp/pos-checkout/'
        data = {
            'items': [{'product_id': self.product.id, 'quantity': 1, 'unit_price': 100}],
            'subtotal': 100,
            'total_amount': 100,
            'customer_mobile': '9988776655',
            'payment_details': {'credit': 100}
        }
        
        # POS currently allows exceeding limit (common in small shops), 
        # but let's see if we want to enforce it. 
        # For now, our implementation doesn't block it in create_pos_order.
        # If we wanted to block it, we'd add validation there.
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        mapping.refresh_from_db()
        self.assertEqual(mapping.current_balance, Decimal('150.00'))

    def test_ledger_retrieval(self):
        """Test GET ledger endpoint"""
        mapping = RetailerCustomerMapping.objects.create(
            retailer=self.retailer,
            customer=self.customer_user,
            current_balance=Decimal('100.00')
        )
        CustomerLedger.objects.create(
            mapping=mapping,
            transaction_type='SALE',
            amount=Decimal('100.00'),
            balance_after=Decimal('100.00')
        )
        
        url = reverse('get_customer_ledger', kwargs={'customer_id': self.customer_user.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(float(response.data['results'][0]['amount']), 100.0)
