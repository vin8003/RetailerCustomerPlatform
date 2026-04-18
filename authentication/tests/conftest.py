import pytest
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from rest_framework.throttling import BaseThrottle

# Globally disable throttling for tests
BaseThrottle.allow_request = lambda self, request, view: True

@pytest.fixture
def api_client():
    """Fixture for DRF API Client."""
    return APIClient()

@pytest.fixture
def mock_firebase_auth():
    """Mock for Firebase verify_id_token."""
    with patch('authentication.utils.firebase_auth.verify_id_token') as mock:
        yield mock

@pytest.fixture
def mock_sms_request():
    """Mock for requests.get used in send_sms_otp."""
    with patch('authentication.utils.requests.get') as mock:
        mock.return_value.status_code = 200
        yield mock

@pytest.fixture
def mock_email_send():
    """Mock for django.core.mail.send_mail."""
    with patch('django.core.mail.send_mail') as mock:
        yield mock
