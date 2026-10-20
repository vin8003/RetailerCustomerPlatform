import pytest
from decimal import Decimal

from customers.models import CustomerProfile
from orders.models import RetailerRating
from orders.services.rating_service import apply_retailer_rating_effects


@pytest.mark.django_db
def test_apply_retailer_rating_effects_updates_profile(order, retailer, customer):
    rating = RetailerRating.objects.create(order=order, retailer=retailer, customer=customer, rating=4)
    apply_retailer_rating_effects(rating)
    profile = CustomerProfile.objects.get(user=customer)
    assert profile.average_rating == Decimal('4.00')
    assert profile.total_ratings == 1
