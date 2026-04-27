import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from django.utils import timezone
from orders.models import Order
from returns.models import SalesReturn

@pytest.mark.django_db
class TestERPReports:
    """
    Test accuracy of ERP Financial Reports
    """

    def test_daily_sales_summary_with_returns(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("get_daily_sales_summary")
        
        # 1. Create a sale today
        Order.objects.create(
            retailer=retailer,
            subtotal=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
            delivery_mode='pickup',
            payment_mode='cash',
            source='pos',
            status='delivered'
        )
        
        # 2. Create a return today
        SalesReturn.objects.create(
            retailer=retailer,
            refund_amount=Decimal("200.00"),
            refund_payment_mode='cash'
        )
        
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        
        # Net Sales = 1000 - 200 = 800
        assert response.data["total_sales"] == 800.0
        assert response.data["cash_sales"] == 800.0
        assert response.data["cash_refunds"] == 200.0

    def test_daily_sales_summary_cross_day_return(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("get_daily_sales_summary")
        
        # Return today for an order that doesn't exist today
        SalesReturn.objects.create(
            retailer=retailer,
            refund_amount=Decimal("150.00"),
            refund_payment_mode='upi'
        )
        
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        
        # Net Sales = 0 - 150 = -150
        assert response.data["total_sales"] == -150.0
        assert response.data["digital_sales"] == -150.0
        assert response.data["upi_refunds"] == 150.0
