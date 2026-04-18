import pytest
from decimal import Decimal
from retailers.serializers import (
    RetailerProfileSerializer, RetailerProfileUpdateSerializer,
    RetailerOperatingHoursUpdateSerializer, RetailerCreateReviewSerializer,
    RetailerListSerializer
)
from retailers.models import RetailerReview


@pytest.mark.django_db
class TestRetailerProfileUpdateSerializer:
    def test_validation_pincode(self):
        data = {"pincode": "12345"} # 5 digits
        serializer = RetailerProfileUpdateSerializer(data=data, partial=True)
        assert not serializer.is_valid()
        assert "pincode" in serializer.errors

    def test_validation_gst(self):
        data = {"gst_number": "12345"} # 5 chars instead of 15
        serializer = RetailerProfileUpdateSerializer(data=data, partial=True)
        assert not serializer.is_valid()
        assert "gst_number" in serializer.errors

    def test_validation_pan(self):
        data = {"pan_number": "ABCDE"} # 5 chars instead of 10
        serializer = RetailerProfileUpdateSerializer(data=data, partial=True)
        assert not serializer.is_valid()
        assert "pan_number" in serializer.errors


@pytest.mark.django_db
class TestRetailerOperatingHoursSerializer:
    def test_invalid_times(self, retailer):
        data = {
            "day_of_week": "monday",
            "is_open": True,
            "opening_time": "18:00:00",
            "closing_time": "09:00:00" # Open > Close
        }
        serializer = RetailerOperatingHoursUpdateSerializer(data=data)
        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors


@pytest.mark.django_db
class TestRetailerReviewSerializer:
    def test_rating_range(self, retailer, customer):
        data = {"rating": 6, "comment": "Too good"}
        serializer = RetailerCreateReviewSerializer(
            data=data, 
            context={"retailer": retailer, "customer": customer}
        )
        assert not serializer.is_valid()
        assert "rating" in serializer.errors

    def test_create_review_updates_retailer_rating(self, retailer, customer):
        data = {"rating": 4, "comment": "Good"}
        serializer = RetailerCreateReviewSerializer(
            data=data, 
            context={"retailer": retailer, "customer": customer}
        )
        assert serializer.is_valid()
        serializer.save()
        retailer.refresh_from_db()
        assert retailer.average_rating == Decimal("4.00")
        assert retailer.total_ratings == 1


@pytest.mark.django_db
class TestRetailerListSerializer:
    def test_distance_in_context(self, retailer):
        # Delhi
        retailer.latitude = Decimal("28.6139")
        retailer.longitude = Decimal("77.2090")
        retailer.save()
        
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user_location = (19.0760, 72.8777) # Mumbai
        
        serializer = RetailerListSerializer(retailer, context={"request": request})
        assert serializer.data["distance"] is not None
        assert 1140 <= serializer.data["distance"] <= 1160
