import random
import string
import requests
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
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
        if "default credentials" in str(e) or "project ID" in str(e) or "was not found" in str(e) or "No such file" in str(e):
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
    Generate a 6-digit random number OTP
    """
    # Generate 6 random digits
    otp_code = ''.join(random.choices(string.digits, k=6))
    # For compatibility with existing models/views that define secret_key
    # We can just use the same otp_code or a dummy, but let's keep it simple.
    # The models expects a secret_key (char field). 
    # Let's just return the otp_code as both for now, or generate a random string for secret if needed for some other reason?
    # The views use: otp_code, secret_key = generate_otp()
    # verify_otp_helper(otp_verification.secret_key, otp_code)
    # The new verify helper will just compare strings.
    # So we don't strictly need a "secret key" like TOTP does.
    # But to satisfy the function signature and db model:
    secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    return otp_code, secret_key


def verify_otp_helper(secret_key, otp_code, expected_otp=None):
    """
    Verify the OTP code. 
    New logic: Direct comparison with expected_otp if provided, 
    otherwise falls back to old TOTP logic if we still needed it (we don't).
    Actually, the view passes (otp_verification.secret_key, otp_code).
    Code in view: verify_otp_helper(otp_verification.secret_key, otp_code)
    WAIT. The view currently retrieves the `OTPVerification` object. 
    The `OTPVerification` object has `otp_code` and `secret_key`.
    The `verify_otp` view receives `otp_code` from request.
    
    We should change the view to pass the stored otp_code from DB for comparison.
    But to avoid changing ALL call sites of verify_otp_helper right now if possible (though there is only one main one),
    let's see.
    
    If I change `generate_otp` to return (otp, secret), `secret` is not really used for verification anymore in my new plan, 
    the `otp_code` stored in DB is used.
    
    However, the PREVIOUS `verify_otp` view implementation:
    `if verify_otp_helper(otp_verification.secret_key, otp_code):`
    
    It passes the STORED secret key and the USER PROVIDED otp code.
    It does NOT pass the STORED otp code.
    
    So I MUST change the View as well to pass the stored OTP code, OR 
    I can misuse the secret_key field to store the OTP code? No, that's messy.
    
    The `OTPVerification` model ALREADY likely has an `otp_code` field. 
    Let's check models.py to be sure ... I saw it in `views.py` usage:
    `otp_verification = OTPVerification.objects.create(..., otp_code=otp_code, secret_key=secret_key, ...)`
    
    Yes, it has both.
    
    So, I will change `verify_otp_helper` to accept `stored_otp` and `input_otp`.
    But `views.py` passes `secret_key` currently.
    
    So I will update `verify_otp_helper` to:
    `def verify_otp_helper(stored_otp, input_otp): return stored_otp == input_otp`
    
    And I will update `views.py` to call it correctly.
    """
    if expected_otp is not None:
         return str(expected_otp) == str(otp_code)
    return False


def _send_sms_otp_thread(phone_number, otp_code, api_key, api_url, sender_id, pe_id=None, template_id=None):
    """
    Internal function to send SMS in a background thread using Authkey.io
    """
    try:
        # Prepare parameters for Authkey
        # Extracts country code if present, default to 91
        country_code = "91"
        mobile = phone_number

        if phone_number.startswith('+91'):
            country_code = "91"
            mobile = phone_number[3:]
        elif phone_number.startswith('+'):
            # Basic fallback for other country codes if needed, 
            # or just strip '+' and try to find logic, but for now assuming India/Default or manual entry
            mobile = phone_number[1:]
            # Ideally we might parse more intelligently, but sticking to +91 support for now

        params = {
            'authkey': api_key,
            'sms': f'Your OTP code is {otp_code}. Valid for 5 minutes. Do not share this code.',
            'mobile': mobile,
            'country_code': country_code,
            'sender': sender_id
        }
        
        if pe_id:
            params['pe_id'] = pe_id
        if template_id:
            params['template_id'] = template_id

        # Authkey uses GET request
        response = requests.get(api_url, params=params, timeout=10)

        if response.status_code == 200:
            logger.info(f"SMS sent successfully to {phone_number}")
        else:
            logger.error(f"Failed to send SMS: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error sending SMS in thread: {str(e)}")

def send_sms_otp(phone_number, otp_code):
    """
    Send OTP via SMS using Authkey.io
    Runs in a separate thread.
    """
    try:
        # For development/testing, just log the OTP if needed, 
        # but User asked for updates so we prioritize their key. 
        # However, keeping debug bypass is good practice IF configured.
        # if settings.DEBUG:
        #      logger.info(f"SMS OTP (DEBUG MODE): {otp_code} for {phone_number}")
        #      # We can still send it if we want to test the API even in debug.
        #      # But usually we don't want to waste credits. 
        #      # Let's comment out return to allow testing or keep it if strictly dev.
        #      # User gave a key, they probably want to test it.
        #      # I'll log it and PROCEED to send it for now, or maybe check a flag?
        #      # Standard practice: Debug mode = no SMS. 
        #      # I will keep valid behavior: Log and Return True.
        #      return True

        api_key = settings.AUTHKEY_API_KEY
        api_url = settings.AUTHKEY_URL
        sender_id = settings.AUTHKEY_SENDER
        pe_id = settings.AUTHKEY_PE_ID
        template_id = settings.AUTHKEY_TEMPLATE_ID

        if not api_key:
            logger.error("Authkey API key not found in settings")
            return False

        import threading
        thread = threading.Thread(
            target=_send_sms_otp_thread,
            args=(phone_number, otp_code, api_key, api_url, sender_id, pe_id, template_id)
        )
        thread.start()
        
        return True

    except Exception as e:
        logger.error(f"Error initiating SMS thread: {str(e)}")
        return False

    except Exception as e:
        logger.error(f"Error initiating SMS thread: {str(e)}")
        return False


def send_email_otp(email, otp_code, purpose):
    """
    Send OTP via email using configured SMTP credentials.
    """
    try:
        subject_map = {
            'signup': 'Verify your email address',
            'password_reset': 'Reset your password',
        }
        subject = subject_map.get(purpose, 'Your verification code')
        message = (
            f"Your OTP code is {otp_code}. "
            "It is valid for 5 minutes. Do not share this code."
        )

        if not settings.EMAIL_HOST_USER:
            logger.error("Email host user not found in settings")
            return False

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        logger.info(f"Email OTP sent to {email} for {purpose}")
        return True
    except Exception as e:
        logger.error(f"Error sending email OTP: {str(e)}")
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
