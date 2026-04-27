import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework import status
from cart.models import Cart, CartItem
from offers.models import Offer, OfferTarget

@pytest.mark.django_db
class TestCartViewEdges:
    
    def test_add_to_cart_wrong_user_type(self, api_client, retailer_user):
        # Trigger line 98: if request.user.user_type != 'customer'
        api_client.force_authenticate(user=retailer_user)
        url = reverse('add_to_cart')
        response = api_client.post(url, {})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['error'] == 'Only customers can add items to cart'

    @patch('cart.views.AddToCartSerializer.is_valid')
    def test_add_to_cart_exception(self, mock_is_valid, api_client, customer):
        # Trigger lines 123-125: except Exception as e
        api_client.force_authenticate(user=customer)
        mock_is_valid.side_effect = Exception("Cart error")
        url = reverse('add_to_cart')
        response = api_client.post(url, {})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_bxgy_auto_add_logic_branches(self, api_client, customer, retailer, product):
        # Test line 514-556: _apply_same_product_auto_add
        api_client.force_authenticate(user=customer)
        
        # Create a BXGY 1+1 Offer (Group size 2)
        offer = Offer.objects.create(
            retailer=retailer, name="BOGO", offer_type="bxgy",
            buy_quantity=1, get_quantity=1, is_active=True,
            bxgy_strategy='same_product', value=0
        )
        # Offer Target - Product
        OfferTarget.objects.create(offer=offer, target_type="product", product=product)
        
        # Add 1 item. Remainder = 1 % 2 = 1. 1 >= buy_qty(1). 
        # So should auto-add 2-1 = 1. Total 2.
        url = reverse('add_to_cart')
        data = {'product_id': product.id, 'quantity': 1}
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        
        cart_item = CartItem.objects.get(product=product, cart__customer=customer)
        assert cart_item.quantity == 2

    @patch('cart.views.Cart.objects.get')
    def test_cart_clear_exception(self, mock_get, api_client, customer, retailer):
        # Trigger lines 277-279 in cart/views.py
        api_client.force_authenticate(user=customer)
        mock_get.side_effect = Exception("Clear fail")
        url = reverse('clear_cart')
        response = api_client.post(url, {'retailer_id': retailer.id})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch('cart.views.UpdateCartItemSerializer.is_valid')
    def test_update_cart_item_exception(self, mock_is_valid, api_client, customer, retailer, product):
        # Trigger generic exception in update_cart_item
        api_client.force_authenticate(user=customer)
        mock_is_valid.side_effect = Exception("Update error")
        
        cart, _ = Cart.objects.get_or_create(customer=customer, retailer=retailer)
        item = CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=10)
        
        url = reverse('update_cart_item', kwargs={'item_id': item.id})
        response = api_client.put(url, {'quantity': 5})
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
