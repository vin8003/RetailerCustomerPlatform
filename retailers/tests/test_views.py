import pytest
from django.urls import reverse
from rest_framework import status
from decimal import Decimal
from retailers.models import RetailerProfile, RetailerOperatingHours, RetailerReview


@pytest.mark.django_db
class TestRetailerProfileViews:
    def test_get_profile(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        url = reverse('get_retailer_profile')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['shop_name'] == retailer.shop_name

    def test_create_profile(self, api_client):
        from authentication.models import User
        new_retailer_user = User.objects.create_user(
            username="new_ret", email="nr@t.com", password="P", user_type="retailer"
        )
        api_client.force_authenticate(user=new_retailer_user)
        url = reverse('create_retailer_profile')
        data = {
            "shop_name": "New Shop",
            "address_line1": "Road 1",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001"
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        # Verify default operating hours were created
        profile = RetailerProfile.objects.get(user=new_retailer_user)
        assert RetailerOperatingHours.objects.filter(retailer=profile).count() == 7

    def test_update_profile(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        url = reverse('update_retailer_profile')
        data = {"shop_description": "Updated description"}
        response = api_client.patch(url, data)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['shop_description'] == "Updated description"


@pytest.mark.django_db
class TestRetailerListViews:
    def test_list_retailers_filtering(self, api_client, retailer):
        url = reverse('list_retailers')
        
        # City match
        response = api_client.get(url, {"city": "TestCity"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) == 1
        
        # Pincode mismatch
        response = api_client.get(url, {"pincode": "000000"})
        assert len(response.data['results']) == 0

    def test_list_retailers_distance(self, api_client, retailer):
        # Delhi
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.delivery_radius = 20 # 20km
        retailer.save()
        
        url = reverse('list_retailers')
        
        # Near New Delhi (10km away)
        # 28.6139, 77.1090 is approx 9.7km away
        response = api_client.get(url, {"lat": 28.6139, "lng": 77.1090})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) == 1
        
        # Far away (Mumbai)
        response = api_client.get(url, {"lat": 19.0760, "lng": 72.8777})
        assert len(response.data['results']) == 0


@pytest.mark.django_db
class TestRetailerSettingsViews:
    def test_update_operating_hours(self, api_client, retailer_user, retailer, operating_hours):
        api_client.force_authenticate(user=retailer_user)
        url = reverse('update_operating_hours')
        
        data = {
            "operating_hours": [
                {
                    "day_of_week": "monday",
                    "is_open": False
                }
            ]
        }
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        operating_hours.refresh_from_db()
        assert operating_hours.is_open is False


@pytest.mark.django_db
class TestRetailerReviewViews:
    def test_create_review(self, api_client, customer, retailer):
        api_client.force_authenticate(user=customer)
        url = reverse('create_retailer_review', kwargs={'retailer_id': retailer.id})
        data = {"rating": 5, "comment": "Excellent!"}
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert RetailerReview.objects.filter(retailer=retailer, customer=customer).exists()
