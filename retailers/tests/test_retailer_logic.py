import pytest
from .factories import RetailerProfileFactory, RetailerOperatingHoursFactory, RetailerCustomerMappingFactory
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()

@pytest.mark.django_db
class TestRetailerLogic:
    def test_distance_calculation(self):
        # Mumbai (Gateway of India)
        retailer = RetailerProfileFactory(latitude=18.9220, longitude=72.8347)
        # Marine Drive (approx 3km away)
        lat_marine, lng_marine = 18.9431, 72.8230
        
        distance = retailer.get_distance_from(lat_marine, lng_marine)
        
        assert distance is not None
        assert 2.0 < distance < 4.0  # Should be around 2.6km

    def test_crm_mapping_creation(self):
        retailer = RetailerProfileFactory()
        customer = User.objects.create_user(username="cust1", phone_number="+919999911111")
        
        mapping = RetailerCustomerMappingFactory(retailer=retailer, customer=customer, nickname="John Doe")
        
        assert mapping.nickname == "John Doe"
        assert mapping.customer_type == 'online'
        assert retailer.customer_mappings.count() == 1

    def test_operating_hours_link(self):
        retailer = RetailerProfileFactory()
        hours = RetailerOperatingHoursFactory(retailer=retailer, day_of_week="monday", opening_time="08:00:00", closing_time="22:00:00")
        
        assert retailer.operating_hours.count() == 1
        assert retailer.operating_hours.first().day_of_week == "monday"
