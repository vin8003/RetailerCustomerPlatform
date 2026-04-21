import pytest
from django.urls import reverse
from rest_framework import status
from customers.models import CustomerProfile, CustomerAddress, CustomerLoyalty
from retailers.models import RetailerProfile

@pytest.mark.django_db
class TestCustomerPhase2:

    def test_customer_profile_flow(self, api_client, customer):
        # Trigger get_customer_profile and update_customer_profile
        api_client.force_authenticate(user=customer)
        
        # Get Profile
        url = reverse('get_customer_profile')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        
        # Update Profile
        url_update = reverse('update_customer_profile')
        response = api_client.patch(url_update, {'first_name': 'UpdatedName'})
        assert response.status_code == status.HTTP_200_OK
        
        customer.refresh_from_db()
        assert customer.first_name == 'UpdatedName'

    def test_customer_address_crud_cycle(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        
        # 1. Create Address
        url_create = reverse('create_customer_address')
        data = {
            'title': 'Home',
            'address_line1': '123 Test St',
            'city': 'TestCity',
            'state': 'TestState',
            'pincode': '123456',
            'is_default': True
        }
        response = api_client.post(url_create, data)
        assert response.status_code == status.HTTP_201_CREATED
        address_id = response.data['id']
        
        # 2. List Addresses
        url_list = reverse('get_customer_addresses')
        response = api_client.get(url_list)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1
        
        # 3. Get Specific Address
        url_get = reverse('get_customer_address', kwargs={'address_id': address_id})
        response = api_client.get(url_get)
        assert response.status_code == status.HTTP_200_OK
        
        # 4. Update Address
        url_update = reverse('update_customer_address', kwargs={'address_id': address_id})
        response = api_client.patch(url_update, {'address_line1': '456 New St'})
        assert response.status_code == status.HTTP_200_OK
        
        # 5. Delete Address (Soft delete)
        url_delete = reverse('delete_customer_address', kwargs={'address_id': address_id})
        response = api_client.delete(url_delete)
        assert response.status_code == status.HTTP_200_OK
        
        # Verify inactive
        addr = CustomerAddress.objects.get(id=address_id)
        assert addr.is_active is False

    def test_get_customer_dashboard_success(self, api_client, customer):
        # Trigger get_customer_dashboard (Lines 459-479)
        api_client.force_authenticate(user=customer)
        url = reverse('get_customer_dashboard')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert 'total_orders' in response.data

    def test_get_retailer_customers_loyalty_view(self, api_client, retailer, customer):
        # Trigger get_retailer_customers_loyalty (Lines 695-715)
        CustomerLoyalty.objects.create(customer=customer, retailer=retailer, points=100)
        
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_customers_loyalty')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1
        assert response.data[0]['points'] == 100

    def test_referral_system_flow(self, api_client, retailer, customer):
        # Trigger apply_referral_code (Lines 733-763+)
        from retailers.models import RetailerRewardConfig
        RetailerRewardConfig.objects.create(retailer=retailer, is_referral_enabled=True)
        
        # Create a referrer
        from django.contrib.auth import get_user_model
        User = get_user_model()
        referrer_user = User.objects.create_user(username='referrer', password='password', user_type='customer')
        referrer_profile = CustomerProfile.objects.create(user=referrer_user, referral_code='REF123')
        
        api_client.force_authenticate(user=customer)
        url = reverse('apply_referral_code')
        data = {
            'referral_code': 'REF123',
            'retailer_id': retailer.id
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED

    def test_retailer_blacklist_toggle(self, api_client, retailer, customer):
        # Trigger toggle_blacklist (Lines 1056-1076+)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('toggle_blacklist')
        
        # Blacklist
        data_bl = {'customer_id': customer.id, 'action': 'blacklist', 'reason': 'Bad behavior'}
        response = api_client.post(url, data_bl)
        assert response.status_code == status.HTTP_200_OK
        
        # Unblacklist
        data_ubl = {'customer_id': customer.id, 'action': 'unblacklist'}
        response = api_client.post(url, data_ubl)
        assert response.status_code == status.HTTP_200_OK

    def test_loyalty_transaction_listing(self, api_client, retailer, customer):
        # Trigger get_loyalty_transactions (Lines 824-863)
        from customers.models import LoyaltyTransaction
        LoyaltyTransaction.objects.create(
            customer=customer, 
            retailer=retailer, 
            amount=50, 
            transaction_type='earn'
        )
        
        api_client.force_authenticate(user=customer)
        url = reverse('get_loyalty_transactions')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1

    def test_get_retailer_customer_management_views(self, api_client, retailer, customer):
        # Trigger get_retailer_customers and get_customer_details_for_retailer
        from orders.models import Order
        from decimal import Decimal
        from retailers.models import RetailerCustomerMapping
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=customer, customer_type='online')
        Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_mode='delivery',
            payment_mode='cod',
            subtotal=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            status='delivered'
        )
        
        api_client.force_authenticate(user=retailer.user)
        
        # 1. Retailer Customer List
        url_list = reverse('get_retailer_customers')
        response = api_client.get(url_list)
        assert response.status_code == status.HTTP_200_OK
        
        # 2. Retailer Customer Detail
        url_detail = reverse('get_customer_details_for_retailer', kwargs={'customer_id': customer.id})
        response = api_client.get(url_detail)
        assert response.status_code == status.HTTP_200_OK

    def test_customer_notifications_and_rewards(self, api_client, customer, notification, retailer):
        # Trigger get_customer_notifications, mark_notification_read, get_reward_configuration
        api_client.force_authenticate(user=customer)
        
        # 1. Notifications
        url_notif = reverse('get_customer_notifications')
        response = api_client.get(url_notif)
        assert response.status_code == status.HTTP_200_OK
        
        # 2. Mark Read
        url_read = reverse('mark_notification_read', kwargs={'notification_id': notification.id})
        response = api_client.patch(url_read)
        assert response.status_code == status.HTTP_200_OK
        
        # 3. Reward config (public/customer)
        url_rew = reverse('get_reward_configuration')
        response = api_client.get(url_rew, {'retailer_id': retailer.id})
        assert response.status_code == status.HTTP_200_OK
