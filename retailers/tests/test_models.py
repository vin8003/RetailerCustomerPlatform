import pytest
from decimal import Decimal
from retailers.models import (
    RetailerProfile, RetailerOperatingHours, RetailerCategory,
    RetailerCategoryMapping, RetailerReview, RetailerRewardConfig,
    RetailerBlacklist
)


@pytest.mark.django_db
class TestRetailerProfile:
    def test_str(self, retailer):
        assert "Products Test Shop" in str(retailer)
        assert "TestCity" in str(retailer)

    def test_full_address(self, retailer):
        assert "123 Main St" in retailer.full_address
        assert "TestCity" in retailer.full_address
        assert "123456" in retailer.full_address

    def test_distance_calculation(self, retailer):
        # New Delhi coordinates
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.save()
        
        # Mumbai coordinates
        mumbai_lat = 19.0760
        mumbai_lng = 72.8777
        
        distance = retailer.get_distance_from(mumbai_lat, mumbai_lng)
        # Approximate distance New Delhi to Mumbai is ~1148km
        assert 1140 <= distance <= 1160

    def test_distance_none_coords(self, retailer):
        retailer.latitude = None
        retailer.save()
        assert retailer.get_distance_from(0, 0) is None


@pytest.mark.django_db
class TestRetailerOperatingHours:
    def test_str(self, operating_hours):
        assert "Products Test Shop" in str(operating_hours)
        assert "monday" in str(operating_hours)


@pytest.mark.django_db
class TestRetailerCategory:
    def test_str(self, retailer_category):
        assert str(retailer_category) == "Pharmacy"


@pytest.mark.django_db
class TestRetailerCategoryMapping:
    def test_str(self, retailer, retailer_category):
        mapping = RetailerCategoryMapping.objects.create(
            retailer=retailer,
            category=retailer_category,
            is_primary=True
        )
        assert "Products Test Shop" in str(mapping)
        assert "Pharmacy" in str(mapping)


@pytest.mark.django_db
class TestRetailerReview:
    def test_str(self, retailer, customer):
        review = RetailerReview.objects.create(
            retailer=retailer,
            customer=customer,
            rating=5,
            comment="Great shop!"
        )
        assert "Products Test Shop" in str(review)
        assert "5 stars" in str(review)


@pytest.mark.django_db
class TestRetailerRewardConfig:
    def test_str(self, reward_config):
        assert "Reward Config for Products Test Shop" in str(reward_config)


@pytest.mark.django_db
class TestRetailerBlacklist:
    def test_str(self, retailer, customer):
        blacklist = RetailerBlacklist.objects.create(
            retailer=retailer,
            customer=customer,
            reason="Repeated cancellations"
        )
        assert customer.username in str(blacklist)
        assert "Products Test Shop" in str(blacklist)
