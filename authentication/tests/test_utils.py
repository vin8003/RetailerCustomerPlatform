import pytest
from unittest.mock import patch, MagicMock
from django.conf import settings
from authentication.utils import (
    verify_firebase_id_token, generate_otp, verify_otp_helper,
    _send_sms_otp_thread, send_sms_otp, _send_email_otp_thread, send_email_otp,
    clean_phone_number, is_valid_phone_number, generate_username_from_phone,
    rate_limit_user, log_security_event, get_client_ip, mask_phone_number,
    create_session_token, hash_token
)

@pytest.fixture
def override_authkey_settings(settings):
    settings.AUTHKEY_API_KEY = "test_key"
    settings.AUTHKEY_URL = "http://test.url"
    settings.AUTHKEY_SENDER = "SENDER"
    settings.AUTHKEY_PE_ID = "PE"
    settings.AUTHKEY_TEMPLATE_ID = "TEMP"
    return settings

class TestAuthenticationUtils:
    
    @patch('authentication.utils.firebase_auth.verify_id_token')
    def test_verify_firebase_id_token_success(self, mock_verify):
        mock_verify.return_value = {"uid": "123"}
        assert verify_firebase_id_token("token") == {"uid": "123"}

    @patch('authentication.utils.firebase_auth.verify_id_token')
    def test_verify_firebase_id_token_value_error(self, mock_verify):
        mock_verify.side_effect = ValueError("Invalid token")
        assert verify_firebase_id_token("badToken") is None

    @patch('authentication.utils.firebase_auth.verify_id_token')
    @patch('authentication.utils.jwt.decode')
    def test_verify_firebase_id_token_dev_fallback(self, mock_decode, mock_verify, settings):
        settings.DEBUG = True
        mock_verify.side_effect = Exception("default credentials project ID was not found")
        mock_decode.return_value = {"uid": "mocked"}
        assert verify_firebase_id_token("mock") == {"uid": "mocked"}
        
        # Test decode failure inside fallback
        mock_decode.side_effect = Exception("decode error")
        assert verify_firebase_id_token("mock") is None

    @patch('authentication.utils.firebase_auth.verify_id_token')
    def test_verify_firebase_id_token_general_exception(self, mock_verify):
        mock_verify.side_effect = Exception("Some other error")
        assert verify_firebase_id_token("mock") is None

    def test_verify_otp_helper(self):
        assert verify_otp_helper("secret", "123456", expected_otp="123456") is True
        assert verify_otp_helper("secret", "123456", expected_otp="654321") is False
        assert verify_otp_helper("secret", "123456") is False

    @patch('authentication.utils.requests.get')
    def test_send_sms_otp_thread(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        # Call with +91
        _send_sms_otp_thread("+911234567890", "123456", "key", "url", "sender", "pe", "temp")
        mock_get.assert_called()
        
        # Call with just +
        _send_sms_otp_thread("+11234567890", "123456", "key", "url", "sender")
        
        # Test error handling
        mock_response.status_code = 400
        _send_sms_otp_thread("+911234567890", "123456", "key", "url", "sender")
        
        # Exception block
        mock_get.side_effect = Exception("Net down")
        _send_sms_otp_thread("+911234567890", "123456", "key", "url", "sender")

    @patch('threading.Thread')
    def test_send_sms_otp(self, mock_thread, override_authkey_settings):
        # Happy patch
        assert send_sms_otp("+911234567890", "123456") is True
        mock_thread.assert_called()
        
        # Missing key
        override_authkey_settings.AUTHKEY_API_KEY = None
        assert send_sms_otp("+91", "12") is False

        # Thread exception
        override_authkey_settings.AUTHKEY_API_KEY = "test"
        mock_thread.side_effect = Exception("thread limit")
        assert send_sms_otp("+911", "1") is False

    @patch('django.core.mail.send_mail')
    def test_send_email_otp_thread(self, mock_send):
        _send_email_otp_thread("test@example.com", "123456")
        mock_send.assert_called()
        
        mock_send.side_effect = Exception("smtp err")
        _send_email_otp_thread("test@example.com", "123456")

    @patch('threading.Thread')
    def test_send_email_otp(self, mock_thread):
        assert send_email_otp("test@example.com", "1234") is True
        
        mock_thread.side_effect = Exception("thread limit")
        assert send_email_otp("a@b.com", "1") is False

    def test_is_valid_phone_number(self):
        assert is_valid_phone_number("+12345678901") is True
        assert is_valid_phone_number("123") is False
        assert is_valid_phone_number(None) is False # triggers except block

    def test_generate_username_from_phone(self):
        assert generate_username_from_phone("+91 12345") == "user_9112345"

    @patch('authentication.utils.cache')
    def test_rate_limit_user(self, mock_cache):
        # 1st attempt: 0 -> returns True
        # 2nd attempt: 1 -> returns True
        # 3rd attempt: 2 -> returns False
        mock_cache.get.side_effect = [0, 1, 2]
        
        assert rate_limit_user("test", max_attempts=2) is True
        assert rate_limit_user("test", max_attempts=2) is True
        assert rate_limit_user("test", max_attempts=2) is False

    def test_log_security_event(self):
        log_security_event("LOGIN", user_id=1, ip_address="127.0.0.1", details="None")
        
    def test_get_client_ip(self):
        class MockReq:
            def __init__(self, meta):
                self.META = meta
        
        r1 = MockReq({'HTTP_X_FORWARDED_FOR': '1.1.1.1, 2.2.2.2'})
        assert get_client_ip(r1) == '1.1.1.1'
        
        r2 = MockReq({'REMOTE_ADDR': 'localhost'})
        assert get_client_ip(r2) == 'localhost'

    def test_mask_phone_number(self):
        assert mask_phone_number("+1234567890") == "+123***7890"
        assert mask_phone_number("123") == "123"

    def test_create_session_token(self):
        assert len(create_session_token()) == 32

    def test_hash_token(self):
        h = hash_token("token")
        assert len(h) == 64
        assert type(h) == str
