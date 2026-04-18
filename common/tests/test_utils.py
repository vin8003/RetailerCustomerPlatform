import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from datetime import datetime, time
import pytz
from django.core.files.uploadedfile import SimpleUploadedFile
from common.utils import (
    generate_upload_path, validate_image_file, validate_document_file,
    format_phone_number, validate_phone_number, mask_email, mask_phone,
    calculate_distance, get_retailer_status, format_currency,
    generate_otp, paginate_queryset
)

class MockInstance:
    class Meta:
        pass
    def __init__(self):
        self.__class__.__name__ = "TestModel"

@pytest.mark.django_db
class TestCommonUtils:
    
    def test_generate_upload_path(self):
        instance = MockInstance()
        path = generate_upload_path(instance, "image.jpg")
        assert "uploads/testmodel/" in path.lower()
        assert path.endswith(".jpg")

    def test_validate_image_file(self):
        # Valid
        valid_file = SimpleUploadedFile("test.jpg", b"content", content_type="image/jpeg")
        is_valid, msg = validate_image_file(valid_file)
        assert is_valid is True
        
        # Invalid extension
        invalid_ext = SimpleUploadedFile("test.txt", b"content", content_type="text/plain")
        is_valid, msg = validate_image_file(invalid_ext)
        assert is_valid is False
        assert "not supported" in msg

        # Too large
        large_file = MagicMock(size=6 * 1024 * 1024, name="large.jpg")
        is_valid, msg = validate_image_file(large_file)
        assert is_valid is False
        assert "exceed 5MB" in msg

    def test_validate_document_file(self):
        valid_file = SimpleUploadedFile("doc.pdf", b"content", content_type="application/pdf")
        assert validate_document_file(valid_file)[0] is True
        
        invalid_file = SimpleUploadedFile("script.py", b"content")
        assert validate_document_file(invalid_file)[0] is False

    def test_phone_number_utils(self):
        # Format
        assert format_phone_number("9876543210") == "+919876543210"
        assert format_phone_number("+91 99999-88888") == "+919999988888"
        
        # Validate
        assert validate_phone_number("9876543210")[0] is True
        assert validate_phone_number("123")[0] is False

    def test_masking_utils(self):
        assert mask_email("johndoe@example.com") == "j*****e@example.com"
        assert mask_email("ab@c.com") == "ab@c.com" # Too short to mask
        # "+911234567890" len=13. 13-4=9 stars.
        assert mask_phone("+911234567890") == "+9" + "*" * 9 + "90"

    def test_calculate_distance(self):
        # Delhi to Mumbai ~1148km
        dist = calculate_distance(28.6139, 77.2090, 19.0760, 72.8777)
        assert 1140 <= dist <= 1160

    def test_format_currency(self):
        assert format_currency(1234.56) == "₹1,234.56"

    def test_generate_otp(self):
        otp = generate_otp(4)
        assert len(otp) == 4
        assert otp.isdigit()

    def test_paginate_queryset(self):
        items = list(range(50))
        paginated = paginate_queryset(items, page_size=10, page_number=2)
        assert paginated['results'] == list(range(10, 20))
        assert paginated['count'] == 50
        assert paginated['num_pages'] == 5
        assert paginated['current_page'] == 2

    @patch('common.utils.datetime')
    def test_get_retailer_status(self, mock_datetime_class, retailer):
        from retailers.models import RetailerOperatingHours
        # Setup: Open Monday 9-18
        RetailerOperatingHours.objects.get_or_create(
            retailer=retailer, day_of_week="monday", 
            defaults={"is_open": True, "opening_time": time(9, 0), "closing_time": time(18, 0)}
        )
        
        tz = pytz.timezone('Asia/Kolkata')
        
        # Test Open Case: Monday 10:00 AM
        fixed_dt = tz.localize(datetime(2023, 10, 2, 10, 0))
        # When calling datetime.now(tz), it should return our fixed_dt
        mock_datetime_class.now.return_value = fixed_dt
        
        status = get_retailer_status(retailer)
        assert status['is_open'] is True
        assert "Closes at 06:00 PM" in status['next_status_time']

        # Test Closed: Monday 8:00 AM
        mock_datetime_class.now.return_value = tz.localize(datetime(2023, 10, 2, 8, 0))
        status = get_retailer_status(retailer)
        assert status['is_open'] is False
        assert "Opens today at 09:00 AM" in status['next_status_time']
