import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductBatch, ProductInventoryLog
from orders.models import Order
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.mark.django_db
class TestPOSAdvanced:
    """
    Advanced POS tests:
    - Shadow user creation
    - Rupee rounding logic
    - Stock reduction safety
    """

    def test_create_pos_order_shadow_user(self, api_client, retailer_user, product):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("create_pos_order")
        
        mobile = "9988776655"
        data = {
            "customer_name": "New Walk-in",
            "customer_mobile": mobile,
            "payment_mode": "cash",
            "subtotal": 100.00,
            "total_amount": 100.00,
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": 100.00
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        # Verify Shadow User
        user = User.objects.get(phone_number=mobile)
        assert user.registration_status == 'shadow'
        assert user.first_name == "New Walk-in"
        
        # Verify CRM Mapping
        from retailers.models import RetailerCustomerMapping
        assert RetailerCustomerMapping.objects.filter(customer=user).exists()

    def test_pos_rounding_logic(self, api_client, retailer_user, product):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("create_pos_order")
        
        # Subtotal with decimals
        data = {
            "subtotal": 100.55,
            "discount_amount": 5.25,
            "total_amount": 95.30, # 100.55 - 5.25 = 95.30 -> should round to 95
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": 100.55
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        order = Order.objects.get(id=response.data['order']['id'])
        # 100.55 rounds to 101
        # 5.25 rounds to 5
        # 95.30 rounds to 95
        assert order.subtotal == Decimal("101.00")
        assert order.discount_amount == Decimal("5.00")
        assert order.total_amount == Decimal("95.00")

    def test_pos_verify_returning_guest(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        
        # Create a past order for a guest
        Order.objects.create(
            retailer=retailer,
            guest_name="Old Guest",
            guest_mobile="9000000001",
            subtotal=100,
            total_amount=100,
            delivery_mode='pickup',
            payment_mode='cash',
            status='delivered'
        )
        
        url = reverse("verify_pos_customer")
        response = api_client.get(url, {"mobile_number": "9000000001"})
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "returning_guest"
        assert response.data["name"] == "Old Guest"
