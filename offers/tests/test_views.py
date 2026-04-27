import pytest
from django.urls import reverse
from rest_framework import status
from decimal import Decimal
from offers.models import Offer


@pytest.mark.django_db
class TestOfferViewSet:
    def test_list_own_offers(self, api_client, retailer_user, retailer):
        Offer.objects.create(retailer=retailer, name="Sale 1", offer_type="percentage", value=10)
        
        # Another retailer's offer
        from authentication.models import User
        other_user = User.objects.create_user(username="other_ret", email="o@t.com", password="P", user_type="retailer")
        from retailers.models import RetailerProfile
        # Create other profile manually to avoid signal reliance if any
        other_retailer = RetailerProfile.objects.create(user=other_user, shop_name="Other Shop")
        Offer.objects.create(retailer=other_retailer, name="Other Sale", offer_type="percentage", value=5)
        
        api_client.force_authenticate(user=retailer_user)
        url = reverse('offer-list')
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        # Handle custom pagination
        results = response.data['results'] if isinstance(response.data, dict) else response.data
        assert len(results) == 1
        assert results[0]['name'] == "Sale 1"

    def test_calculate_cart_preview(self, api_client, retailer_user, retailer, product):
        Offer.objects.create(
            retailer=retailer, name="10% Off", offer_type="percentage",
            value=Decimal("10.00"), is_active=True
        )
        from offers.models import OfferTarget
        OfferTarget.objects.create(offer=Offer.objects.get(name="10% Off"), target_type="all_products")
        
        api_client.force_authenticate(user=retailer_user)
        url = reverse('offer-calculate-cart')
        data = {
            "retailer_id": retailer.id,
            "items": [
                {"product_id": product.id, "quantity": 2, "price": 100}
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert float(response.data['total_savings']) == 20.0
        assert len(response.data['applied_offers']) == 1


@pytest.mark.django_db
class TestPublicOfferViewSet:
    def test_list_public_offers(self, api_client, retailer):
        Offer.objects.create(
            retailer=retailer, name="Public Sale", offer_type="flat_amount", 
            value=50, is_active=True
        )
        Offer.objects.create(
            retailer=retailer, name="Inactive Sale", offer_type="flat_amount", 
            value=100, is_active=False
        )
        
        url = reverse('public-retailer-offers', kwargs={'retailer_id': retailer.id})
        response = api_client.get(url)
        
        assert response.status_code == status.HTTP_200_OK
        results = response.data['results'] if isinstance(response.data, dict) else response.data
        assert len(results) == 1
        assert results[0]['name'] == "Public Sale"
