import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework import status
from customers.models import CustomerProfile, CustomerLoyalty, LoyaltyTransaction
from retailers.models import RetailerRewardConfig

@pytest.mark.django_db
class TestCustomerViewEdges:
    
    def test_get_all_customer_loyalty_empty(self, api_client, customer):
        # Trigger lines 633-656 with no records
        api_client.force_authenticate(user=customer)
        url = reverse('get_all_customer_loyalty')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

    def test_get_all_customer_loyalty_with_data(self, api_client, customer, retailer):
        # Trigger lines 606-656 with mocked data
        api_client.force_authenticate(user=customer)
        CustomerLoyalty.objects.create(customer=customer, retailer=retailer, points=100)
        RetailerRewardConfig.objects.create(retailer=retailer, conversion_rate=1.5)
        LoyaltyTransaction.objects.create(
            customer=customer, retailer=retailer, amount=50, 
            transaction_type='earn', expiry_date='2030-01-01'
        )
        
        url = reverse('get_all_customer_loyalty')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data[0]['points'] == 100.0
        assert response.data[0]['value_in_currency'] == 150.0

    @patch('customers.views.CustomerProfile.objects.get_or_create')
    def test_get_referral_stats_exception(self, mock_get, api_client, customer):
        # Trigger lines 865-866
        api_client.force_authenticate(user=customer)
        mock_get.side_effect = Exception("Referral fail")
        url = reverse('get_referral_stats')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_get_referral_stats_non_customer(self, api_client, retailer_user):
        # Trigger lines 815-819
        api_client.force_authenticate(user=retailer_user)
        url = reverse('get_referral_stats')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
