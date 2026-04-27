import factory
from factory.django import DjangoModelFactory
from authentication.models import User, OTPVerification
from retailers.models import RetailerProfile

class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f'user_{n}')
    email = factory.Sequence(lambda n: f'user_{n}@example.com')
    phone_number = factory.Sequence(lambda n: f'+9190000{n:05d}')
    user_type = 'customer'
    is_active = True

class RetailerUserFactory(UserFactory):
    user_type = 'retailer'

class RetailerProfileFactory(DjangoModelFactory):
    class Meta:
        model = RetailerProfile

    user = factory.SubFactory(RetailerUserFactory)
    shop_name = factory.Faker('company')
    is_active = True
