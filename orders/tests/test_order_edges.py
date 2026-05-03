import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework import status
from decimal import Decimal
from orders.serializers import OrderCreateSerializer
from cart.models import Cart, CartItem
from retailers.models import RetailerRewardConfig
from customers.models import CustomerLoyalty
from orders.models import Order

@pytest.mark.django_db
class TestOrderViewEdges:
    
    def test_verify_order_payment_exception(self, api_client, customer, retailer):
        # Trigger lines 105-107 in orders/views.py
        # MUST BE RETAILER to avoid 403
        api_client.force_authenticate(user=retailer.user)
        # Create a real order with all required fields to avoid IntegrityError
        order = Order.objects.create(
            customer=customer, 
            retailer=retailer, 
            total_amount=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            delivery_mode='delivery',
            payment_mode='upi'
        )
        
        with patch('orders.views.get_object_or_404') as mock_get:
            mock_get.side_effect = Exception("Payment failure")
            url = reverse('verify_payment', kwargs={'order_id': order.id})
            # Action is required to avoid 400
            response = api_client.post(url, {'action': 'verify'})
            # Now it should reach the exception handler and return 500
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_order_points_redemption_math(self, customer, retailer, product):
        # Trigger lines 328-359 in orders/serializers.py
        RetailerRewardConfig.objects.create(
            retailer=retailer, 
            max_reward_usage_percent=10, 
            max_reward_usage_flat=50,
            conversion_rate=1.0,
            is_active=True
        )
        CustomerLoyalty.objects.create(customer=customer, retailer=retailer, points=500)
        
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(cart=cart, product=product, quantity=10, unit_price=100)
        
        data = {
            'retailer_id': retailer.id,
            'use_reward_points': True,
            'delivery_mode': 'delivery',
            'payment_mode': 'upi',
        }
        
        request = MagicMock()
        request.user = customer
        
        from customers.models import CustomerAddress
        mock_addr = CustomerAddress.objects.create(customer=customer, address_line1="Test", is_active=True)
        data['address_id'] = mock_addr.id
        
        serializer = OrderCreateSerializer(data=data, context={'request': request, 'customer': customer})
        assert serializer.is_valid(), serializer.errors
        order = serializer.save()
        # Verify discount_from_points is set
        assert order.discount_from_points == Decimal("50.00")
        assert order.total_amount == Decimal("950.00")


@pytest.mark.django_db
class TestOrderStatusTransitionPolicyEdges:
    def test_valid_transition_still_passes(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.patch(
            reverse('update_order_status', args=[order.id]),
            {'status': 'confirmed'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == 'confirmed'
        assert order.confirmed_at is not None

    def test_invalid_transition_fails_with_existing_error_shape(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.patch(
            reverse('update_order_status', args=[order.id]),
            {'status': 'delivered'},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'status' in response.data
        assert response.data['status'] == ["Cannot change status from 'pending' to 'delivered'"]

    def test_transition_timestamps_unchanged_behavior(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)

        for next_status in ['confirmed', 'processing', 'packed', 'delivered']:
            response = api_client.patch(
                reverse('update_order_status', args=[order.id]),
                {'status': next_status},
                format='json',
            )
            assert response.status_code == status.HTTP_200_OK

        order.refresh_from_db()
        confirmed_at = order.confirmed_at
        delivered_at = order.delivered_at
        cancelled_at = order.cancelled_at

        cancel_response = api_client.patch(
            reverse('update_order_status', args=[order.id]),
            {'status': 'cancelled'},
            format='json',
        )
        assert cancel_response.status_code == status.HTTP_400_BAD_REQUEST

        order.refresh_from_db()
        assert order.confirmed_at == confirmed_at
        assert order.delivered_at == delivered_at
        assert order.cancelled_at == cancelled_at
