import pyotp
import random
import string
import requests
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
import logging

import logging
import firebase_admin
from firebase_admin import auth as firebase_auth
import jwt

logger = logging.getLogger(__name__)


def verify_firebase_id_token(id_token):
    """
    Verify Firebase ID Token
    """
    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
        return decoded_token
    except ValueError as e:
        # Token is invalid (expired, malformed, etc.)
        logger.error(f"Invalid Firebase ID token: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error verifying Firebase ID token: {str(e)}")
        # Handle validation errors
        if "default credentials" in str(e) or "project ID" in str(e):
             if settings.DEBUG:
                 logger.warning("DEVELOPMENT MODE (FIX-647): Credential error detected. Bypassing verification via jwt.decode (unsafe).")
                 try:
                     # Remove 'Bearer ' if present, though verify_id_token usually takes raw JWT
                     unverified_claims = jwt.decode(id_token, options={"verify_signature": False})
                     return unverified_claims
                 except Exception as decode_e:
                     logger.error(f"Failed to decode token for bypass: {decode_e}")
                     return None
        return None


def generate_otp():
    """
    Generate a 6-digit OTP and secret key
    """
    secret_key = pyotp.random_base32()
    totp = pyotp.TOTP(secret_key, interval=300, digits=6)  # 5 minutes validity
    otp_code = totp.now()

    return otp_code, secret_key


def verify_otp_helper(secret_key, otp_code):
    """
    Verify the OTP code against the secret key
    """
    try:
        totp = pyotp.TOTP(secret_key, interval=300, digits=6)
        return totp.verify(otp_code, valid_window=1)
    except Exception as e:
        logger.error(f"Error verifying OTP: {str(e)}")
        return False


def send_sms_otp(phone_number, otp_code):
    """
    Send OTP via SMS using external SMS API
    """
    try:
        # For demo purposes, we'll use a generic SMS API structure
        # In production, replace with actual SMS provider (Twilio, AWS SNS, etc.)

        api_key = settings.SMS_API_KEY
        api_url = settings.SMS_API_URL

        # Example payload structure - adjust based on your SMS provider
        payload = {
            'apikey': api_key,
            'numbers': phone_number,
            'message': f'Your OTP code is: {otp_code}. Valid for 5 minutes. Do not share this code.',
            'sender': 'OrderApp'
        }

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }

        # For development/testing, just log the OTP
        if settings.DEBUG:
            logger.info(f"SMS OTP (DEBUG MODE): {otp_code} for {phone_number}")
            return True

        response = requests.post(api_url, json=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info(f"SMS sent successfully to {phone_number}")
            return True
        else:
            logger.error(f"Failed to send SMS: {response.status_code} - {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"SMS API request failed: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error sending SMS: {str(e)}")
        return False


def clean_phone_number(phone_number):
    """
    Clean and format phone number
    """
    # Remove all non-digit characters except +
    cleaned = ''.join(char for char in phone_number if char.isdigit() or char == '+')

    # Ensure it starts with +
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned

    return cleaned


def is_valid_phone_number(phone_number):
    """
    Basic phone number validation
    """
    try:
        cleaned = clean_phone_number(phone_number)
        # Basic validation - at least 10 digits after country code
        if len(cleaned) < 11:  # +1234567890 minimum
            return False
        return True
    except:
        return False


def generate_username_from_phone(phone_number):
    """
    Generate username from phone number
    """
    return f"user_{phone_number.replace('+', '').replace(' ', '')}"


def rate_limit_user(identifier, max_attempts=5, window_minutes=60):
    """
    Rate limit user actions
    """
    cache_key = f"rate_limit_{identifier}"
    attempts = cache.get(cache_key, 0)

    if attempts >= max_attempts:
        return False

    cache.set(cache_key, attempts + 1, window_minutes * 60)
    return True


def log_security_event(event_type, user_id=None, ip_address=None, details=None):
    """
    Log security-related events
    """
    log_data = {
        'event_type': event_type,
        'user_id': user_id,
        'ip_address': ip_address,
        'details': details,
        'timestamp': datetime.now().isoformat()
    }

    logger.info(f"Security Event: {log_data}")


def get_client_ip(request):
    """
    Get client IP address from request
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def mask_phone_number(phone_number):
    """
    Mask phone number for logging/display purposes
    """
    if len(phone_number) > 4:
        return phone_number[:4] + '*' * (len(phone_number) - 8) + phone_number[-4:]
    return phone_number


def create_session_token():
    """
    Create a unique session token
    """
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))


def hash_token(token):
    """
    Hash a token for secure storage
    """
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()
