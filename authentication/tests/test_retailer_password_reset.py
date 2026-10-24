import pytest
from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import User, OTPVerification, EmailOTPVerification
from authentication.views import RETAILER_RESET_SENT_MESSAGE, RETAILER_RESET_INVALID_MESSAGE

NEW_PASSWORD = "BrandNewPass#2026"


@pytest.fixture
def retailer(db):
    return User.objects.create_user(
        username="shopowner", email="owner@shop.com", password="OldPass#12345",
        user_type="retailer", phone_number="+919876500001",
    )


@pytest.fixture
def sms(mock_sms_request):
    return mock_sms_request


def forgot(client, identifier):
    return client.post(reverse('retailer_forgot_password'), {"identifier": identifier}, format='json')


def reset(client, identifier, code, password=NEW_PASSWORD, confirm=None):
    return client.post(reverse('retailer_reset_password'), {
        "identifier": identifier, "otp_code": code,
        "new_password": password, "confirm_password": confirm or password,
    }, format='json')


@pytest.mark.django_db
class TestRetailerForgotPassword:

    @pytest.mark.parametrize("identifier", ["shopowner", "+919876500001", "9876500001", "OWNER@shop.com"])
    def test_sends_sms_for_every_login_identifier(self, api_client, retailer, sms, identifier):
        res = forgot(api_client, identifier)
        assert res.status_code == status.HTTP_200_OK
        assert res.data['message'] == RETAILER_RESET_SENT_MESSAGE
        rec = OTPVerification.objects.get(user=retailer)
        assert rec.phone_number == "+919876500001"
        assert len(rec.otp_code) == 6

    def test_response_identical_for_unknown_account(self, api_client, retailer, sms):
        known = forgot(api_client, "shopowner")
        unknown = forgot(api_client, "nobody-here")
        assert unknown.status_code == known.status_code == status.HTTP_200_OK
        assert unknown.data == known.data
        assert not OTPVerification.objects.filter(phone_number="nobody-here").exists()

    def test_unknown_phone_and_email_send_nothing(self, api_client, retailer, sms, mock_email_send):
        assert forgot(api_client, "+919000000000").status_code == 200
        assert forgot(api_client, "ghost@nowhere.com").status_code == 200
        assert OTPVerification.objects.count() == 0
        assert EmailOTPVerification.objects.count() == 0

    def test_customer_accounts_cannot_use_retailer_reset(self, api_client, sms):
        User.objects.create_user(username="cust", password="x", user_type="customer", phone_number="+919876500002")
        assert forgot(api_client, "cust").status_code == 200
        assert forgot(api_client, "+919876500002").status_code == 200
        assert OTPVerification.objects.count() == 0

    def test_disabled_retailer_gets_no_code(self, api_client, retailer, sms):
        retailer.is_active = False
        retailer.save()
        assert forgot(api_client, "shopowner").status_code == 200
        assert OTPVerification.objects.count() == 0

    def test_falls_back_to_email_without_phone(self, api_client, sms):
        user = User.objects.create_user(
            username="nophone", email="np@shop.com", password="x", user_type="retailer",
        )
        with patch('authentication.views.send_email_otp', return_value=True) as send:
            assert forgot(api_client, "nophone").status_code == 200
        assert EmailOTPVerification.objects.filter(user=user, email="np@shop.com").exists()
        send.assert_called_once()
        sms.assert_not_called()

    def test_account_with_no_contact_is_silent(self, api_client):
        User.objects.create_user(username="nocontact", password="x", user_type="retailer")
        assert forgot(api_client, "nocontact").status_code == 200

    def test_ambiguous_email_sends_nothing(self, api_client, sms):
        for name in ("a", "b"):
            User.objects.create_user(username=name, email="dup@shop.com", password="x", user_type="retailer")
        assert forgot(api_client, "dup@shop.com").status_code == 200
        assert OTPVerification.objects.count() == 0 and EmailOTPVerification.objects.count() == 0

    def test_resend_cooldown_keeps_first_code(self, api_client, retailer, sms):
        forgot(api_client, "shopowner")
        first = OTPVerification.objects.get(user=retailer).otp_code
        res = forgot(api_client, "shopowner")
        assert res.status_code == 200
        assert OTPVerification.objects.get(user=retailer).otp_code == first
        assert sms.call_count == 1

    def test_resend_after_cooldown_replaces_code(self, api_client, retailer, sms):
        forgot(api_client, "shopowner")
        OTPVerification.objects.update(created_at=timezone.now() - timedelta(seconds=120))
        forgot(api_client, "shopowner")
        assert OTPVerification.objects.filter(user=retailer).count() == 1
        assert sms.call_count == 2

    def test_sms_failure_still_generic(self, api_client, retailer):
        with patch('authentication.views.send_sms_otp', return_value=False):
            res = forgot(api_client, "shopowner")
        assert res.status_code == 200
        assert res.data['message'] == RETAILER_RESET_SENT_MESSAGE

    def test_missing_identifier_is_400(self, api_client):
        assert api_client.post(reverse('retailer_forgot_password'), {}, format='json').status_code == 400


@pytest.mark.django_db
class TestRetailerResetPassword:

    def _request_code(self, client, identifier="shopowner"):
        forgot(client, identifier)
        return OTPVerification.objects.get().otp_code

    def test_full_flow_then_login(self, api_client, retailer, sms):
        code = self._request_code(api_client)
        res = reset(api_client, "shopowner", code)
        assert res.status_code == 200, res.data
        retailer.refresh_from_db()
        assert retailer.check_password(NEW_PASSWORD)
        assert retailer.is_phone_verified
        assert not OTPVerification.objects.exists()
        login = api_client.post(reverse('retailer_login'), {"username": "shopowner", "password": NEW_PASSWORD}, format='json')
        assert login.status_code == 200
        old = api_client.post(reverse('retailer_login'), {"username": "shopowner", "password": "OldPass#12345"}, format='json')
        assert old.status_code == 400

    def test_works_with_phone_identifier(self, api_client, retailer, sms):
        code = self._request_code(api_client, "9876500001")
        assert reset(api_client, "9876500001", code).status_code == 200

    def test_email_code_flow(self, api_client, sms):
        user = User.objects.create_user(username="np", email="np@shop.com", password="x", user_type="retailer")
        with patch('authentication.views.send_email_otp', return_value=True):
            forgot(api_client, "np@shop.com")
        code = EmailOTPVerification.objects.get(user=user).otp_code
        assert reset(api_client, "np", code).status_code == 200
        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD)
        assert not user.is_phone_verified

    def test_code_is_single_use(self, api_client, retailer, sms):
        code = self._request_code(api_client)
        assert reset(api_client, "shopowner", code).status_code == 200
        assert reset(api_client, "shopowner", code, password="AnotherPass#999").status_code == 400
        retailer.refresh_from_db()
        assert retailer.check_password(NEW_PASSWORD)

    def test_wrong_code_counts_attempts_then_locks(self, api_client, retailer, sms):
        code = self._request_code(api_client)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(3):
            res = reset(api_client, "shopowner", wrong)
            assert res.status_code == 400
            assert res.data['error'] == RETAILER_RESET_INVALID_MESSAGE
        # Correct code no longer works once attempts are used up.
        assert reset(api_client, "shopowner", code).status_code == 400
        retailer.refresh_from_db()
        assert retailer.check_password("OldPass#12345")

    def test_expired_code_rejected(self, api_client, retailer, sms):
        code = self._request_code(api_client)
        OTPVerification.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        assert reset(api_client, "shopowner", code).status_code == 400

    def test_same_error_for_unknown_account_and_wrong_code(self, api_client, retailer, sms):
        self._request_code(api_client)
        wrong = reset(api_client, "shopowner", "000000" if OTPVerification.objects.get().otp_code != "000000" else "111111")
        unknown = reset(api_client, "nobody", "123456")
        assert wrong.status_code == unknown.status_code == 400
        assert wrong.data == unknown.data

    def test_code_for_one_account_cannot_reset_another(self, api_client, retailer, sms):
        other = User.objects.create_user(
            username="other", password="OtherPass#1234", user_type="retailer", phone_number="+919876500003",
        )
        code = self._request_code(api_client)
        assert reset(api_client, "other", code).status_code == 400
        other.refresh_from_db()
        assert other.check_password("OtherPass#1234")

    def test_customer_cannot_be_reset_here(self, api_client, sms):
        cust = User.objects.create_user(username="cust", password="CustPass#1234", user_type="customer", phone_number="+919876500002")
        OTPVerification.objects.create(
            user=cust, phone_number=cust.phone_number, otp_code="123456", secret_key="s",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        assert reset(api_client, "cust", "123456").status_code == 400
        cust.refresh_from_db()
        assert cust.check_password("CustPass#1234")

    def test_validation_errors(self, api_client, retailer, sms):
        code = self._request_code(api_client)
        assert reset(api_client, "shopowner", code, confirm="Different#1234").status_code == 400
        assert reset(api_client, "shopowner", code, password="123", confirm="123").status_code == 400
        assert reset(api_client, "shopowner", "12ab56").status_code == 400
        retailer.refresh_from_db()
        assert retailer.check_password("OldPass#12345")
        # validation failures do not burn the code
        assert reset(api_client, "shopowner", code).status_code == 200

    def test_existing_sessions_are_revoked(self, api_client, retailer, sms):
        refresh = RefreshToken.for_user(retailer)
        code = self._request_code(api_client)
        assert reset(api_client, "shopowner", code).status_code == 200
        assert BlacklistedToken.objects.filter(token__user=retailer).exists()
        res = api_client.post(reverse('token_refresh'), {"refresh": str(refresh)}, format='json')
        assert res.status_code == 401


@pytest.mark.django_db
class TestExistingResetHardening:

    def test_phone_reset_locks_after_max_attempts(self, api_client, mock_sms_request):
        user = User.objects.create_user(username="c1", phone_number="+15550001111", password="x")
        api_client.post(reverse('forgot_password'), {"phone_number": "+15550001111"})
        code = OTPVerification.objects.get(user=user).otp_code
        wrong = "000000" if code != "000000" else "111111"
        body = {"phone_number": "+15550001111", "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
        for _ in range(3):
            assert api_client.post(reverse('reset_password'), {**body, "otp_code": wrong}).status_code == 400
        assert api_client.post(reverse('reset_password'), {**body, "otp_code": code}).status_code == 400
        user.refresh_from_db()
        assert not user.check_password(NEW_PASSWORD)

    def test_firebase_token_must_match_phone(self, api_client, mock_firebase_auth):
        user = User.objects.create_user(username="c2", phone_number="+15550002222", password="x")
        mock_firebase_auth.return_value = {"phone_number": "+15550009999"}
        res = api_client.post(reverse('reset_password'), {
            "phone_number": "+15550002222", "firebase_token": "tok",
            "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
        })
        assert res.status_code == 400
        user.refresh_from_db()
        assert not user.check_password(NEW_PASSWORD)
        mock_firebase_auth.return_value = {"phone_number": "+15550002222"}
        res = api_client.post(reverse('reset_password'), {
            "phone_number": "+15550002222", "firebase_token": "tok",
            "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
        })
        assert res.status_code == 200
