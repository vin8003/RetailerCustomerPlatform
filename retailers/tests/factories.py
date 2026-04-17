import factory
from factory.django import DjangoModelFactory
from ..models import RetailerProfile, RetailerCategory, RetailerOperatingHours, RetailerCustomerMapping
from django.contrib.auth import get_user_model

User = get_user_model()

class RetailerCategoryFactory(DjangoModelFactory):
    class Meta:
        model = RetailerCategory
    
    name = factory.Sequence(lambda n: f"Category {n}")
    description = "Test Category"

class RetailerProfileFactory(DjangoModelFactory):
    class Meta:
        model = RetailerProfile
    
    user = factory.SubFactory('authentication.tests.factories.UserFactory')
    shop_name = factory.Sequence(lambda n: f"Shop {n}")
    address_line1 = "123 Main St"
    city = "Mumbai"
    state = "Maharashtra"
    pincode = "400001"
    latitude = 19.0760
    longitude = 72.8777

class RetailerOperatingHoursFactory(DjangoModelFactory):
    class Meta:
        model = RetailerOperatingHours
    
    retailer = factory.SubFactory(RetailerProfileFactory)
    day_of_week = "monday"
    is_open = True
    opening_time = "09:00:00"
    closing_time = "21:00:00"

class RetailerCustomerMappingFactory(DjangoModelFactory):
    class Meta:
        model = RetailerCustomerMapping
    
    retailer = factory.SubFactory(RetailerProfileFactory)
    customer = factory.SubFactory('authentication.tests.factories.UserFactory')
    customer_type = 'online'
