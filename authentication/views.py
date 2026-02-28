from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.contrib.auth import authenticate
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
import logging

from .models import User, OTPVerification, EmailOTPVerification
from fcm_django.models import FCMDevice
from retailers.models import RetailerProfile, RetailerOperatingHours
from .serializers import (
    UserRegistrationSerializer, UserLoginSerializer, OTPRequestSerializer,
    OTPVerificationSerializer, UserProfileSerializer, TokenSerializer,
    PasswordChangeSerializer, RequestPhoneVerificationSerializer,
    ForgotPasswordSerializer, ResetPasswordConfirmSerializer,
    ForgotPasswordEmailSerializer, ResetPasswordEmailConfirmSerializer,
    EmailVerifySerializer
)
from .utils import generate_otp, send_sms_otp, verify_otp_helper, verify_firebase_id_token, send_email_otp

logger = logging.getLogger(__name__)


class LoginThrottle(UserRateThrottle):
    scope = 'login'


class OTPThrottle(AnonRateThrottle):
    scope = 'otp'


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def retailer_signup(request):
    """
    Register a new retailer user
    """
    try:
        data = request.data.copy()
        data['user_type'] = 'retailer'

        serializer = UserRegistrationSerializer(data=data)
        if serializer.is_valid():
            user = serializer.save()

            # Create RetailerProfile with default values
            profile = RetailerProfile.objects.create(
                user=user,
                shop_name=f"{user.first_name or user.username}'s Shop",
                shop_description='',
                business_type='general',
                address_line1='',
                city='',
                state='',
                pincode='000000',
                contact_phone=user.phone_number or '',
                is_active=False,  # Inactive until profile is completed
            )

            # Create default operating hours (Monday to Sunday, 9 AM to 9 PM)
            days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            for day in days:
                RetailerOperatingHours.objects.create(
                    retailer=profile,
                    day_of_week=day,
                    is_open=True,
                    opening_time='09:00',
                    closing_time='21:00'
                )

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            response_data = {
                'message': 'Retailer registered successfully',
                'user': UserProfileSerializer(user).data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                }
            }

            logger.info(f"New retailer registered: {user.username}")
            return Response(response_data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in retailer signup: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def retailer_login(request):
    """
    Login retailer user
    """
    try:
        serializer = UserLoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']

            # Check if user is a retailer
            if user.user_type != 'retailer':
                return Response(
                    {'error': 'Invalid user type for retailer login'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            response_data = {
                'message': 'Login successful',
                'user': UserProfileSerializer(user).data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                }
            }

            logger.info(f"Retailer logged in: {user.username}")
            return Response(response_data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in retailer login: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def customer_signup(request):
    """
    Register a new customer user with password
    """
    try:
        data = request.data.copy()
        data['user_type'] = 'customer'

        serializer = UserRegistrationSerializer(data=data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Customer is active but phone and email not verified
            user.is_active = True
            user.is_phone_verified = False
            user.is_email_verified = False
            user.save()

            # Generate and send Email OTP
            otp_code = generate_otp()
            EmailOTPVerification.objects.update_or_create(
                user=user,
                email=user.email,
                defaults={
                    'otp_code': otp_code,
                    'is_verified': False,
                    'created_at': timezone.now()
                }
            )
            send_email_otp(user.email, otp_code)

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            response_data = {
                'message': 'Customer registered successfully. Please verify your email with the OTP sent.',
                'user': UserProfileSerializer(user).data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                }
            }

            logger.info(f"New customer registered: {user.username}")
            return Response(response_data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in customer signup: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([LoginThrottle])
def customer_login(request):
    """
    Login customer user with password
    """
    try:
        serializer = UserLoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']

            # Check if user is a customer
            if user.user_type != 'customer':
                return Response(
                    {'error': 'Invalid user type for customer login'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if email is verified
            if not user.is_email_verified:
                return Response(
                    {
                        'error': 'Email not verified. Please verify your email to continue.',
                        'email': user.email,
                        'code': 'email_not_verified'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            response_data = {
                'message': 'Login successful',
                'user': UserProfileSerializer(user).data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                }
            }

            logger.info(f"Customer logged in: {user.username}")
            return Response(response_data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in customer login: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([OTPThrottle])
def request_phone_verification(request):
    """
    Request OTP for phone verification (for authenticated users)
    """
    try:
        user = request.user
        phone_number = user.phone_number

        if not phone_number:
            return Response(
                {'error': 'User has no phone number set'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if user.is_phone_verified:
            return Response(
                {'message': 'Phone number already verified'},
                status=status.HTTP_200_OK
            )
        
        # Rate limiting check
        cache_key = f"otp_requests_{phone_number}"
        requests = cache.get(cache_key, 0)
        if requests >= 3:
            return Response(
                {'error': 'Too many OTP requests. Please try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # Generate OTP
        otp_code, secret_key = generate_otp()

        # Update/Create verification record
        OTPVerification.objects.filter(user=user).delete() # Remove old OTPs
        
        otp_verification = OTPVerification.objects.create(
            user=user,
            phone_number=phone_number,
            otp_code=otp_code,
            secret_key=secret_key,
            expires_at=timezone.now() + timezone.timedelta(seconds=settings.OTP_EXPIRY_TIME)
        )

        # Send OTP
        sms_sent = send_sms_otp(phone_number, otp_code)

        if sms_sent:
            cache.set(cache_key, requests + 1, 900)
            logger.info(f"OTP sent to {phone_number} for verification")
            return Response({
                'message': 'OTP sent successfully',
                'phone_number': phone_number,
                'expires_in': settings.OTP_EXPIRY_TIME
            }, status=status.HTTP_200_OK)
        else:
            return Response(
                {'error': 'Failed to send OTP'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    except Exception as e:
        logger.error(f"Error in request_phone_verification: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPThrottle])
def verify_otp(request):
    """
    Verify OTP and complete customer login/signup
    """
    try:
        serializer = OTPVerificationSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            otp_code = serializer.validated_data.get('otp_code')
            firebase_token = serializer.validated_data.get('firebase_token')

            # Firebase Token Verification Flow
            if firebase_token:
                decoded_token = verify_firebase_id_token(firebase_token)
                if decoded_token:
                    # STRICT CHECK: Ensure the token belongs to the phone number being verified
                    token_phone = decoded_token.get('phone_number', '')  # E.g. +919876543210
                    # Normalize both to ensure match (remove spaces, ensure + prefix)
                    
                    def normalize_for_match(p):
                        if not p: return ''
                        p = p.replace(' ', '').replace('-', '')
                        if not p.startswith('+'): p = '+' + p
                        return p

                    if normalize_for_match(token_phone) != normalize_for_match(phone_number):
                        logger.warning(f"Phone mismatch in Firebase Token. Token: {token_phone}, Request: {phone_number}")
                        return Response(
                            {'error': 'Phone number in token does not match requested phone number'},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # User phone verification successful
                    try:
                        # Prefer authenticated user if available
                        if request.user and request.user.is_authenticated:
                            user = request.user
                            # If user verified a different phone number, should we update it?
                            # Yes, creating a seamless "change number and verify" flow.
                            user.phone_number = phone_number 
                            user.is_active = True
                            user.is_phone_verified = True
                            user.save()
                        else:
                            user = User.objects.get(phone_number=phone_number)
                            user.is_active = True
                            user.is_phone_verified = True
                            user.save()

                        
                        # Create or activate RetailerProfile for retailer users
                        if user.user_type == 'retailer':
                            profile, created = RetailerProfile.objects.get_or_create(
                                user=user,
                                defaults={
                                    'shop_name': f"{user.first_name or user.username}'s Shop",
                                    'shop_description': '',
                                    'business_type': 'general',
                                    'address_line1': '',
                                    'city': '',
                                    'state': '',
                                    'pincode': '000000',
                                    'contact_phone': user.phone_number or '',
                                    'is_active': True,
                                }
                            )
                            # Activate existing profile on phone verification
                            if not created and not profile.is_active:
                                profile.is_active = True
                                profile.save()
                                logger.info(f"Activated RetailerProfile for user: {user.username}")
                            elif created:
                                # Create default operating hours for new profile
                                days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                                for day in days:
                                    RetailerOperatingHours.objects.create(
                                        retailer=profile,
                                        day_of_week=day,
                                        is_open=True,
                                        opening_time='09:00',
                                        closing_time='21:00'
                                    )
                                logger.info(f"Created RetailerProfile for user: {user.username}")
                        
                        # Generate JWT tokens
                        refresh = RefreshToken.for_user(user)

                        response_data = {
                            'message': 'Phone verification successful',
                            'user': UserProfileSerializer(user).data,
                            'tokens': {
                                'access': str(refresh.access_token),
                                'refresh': str(refresh),
                            }
                        }
                        return Response(response_data, status=status.HTTP_200_OK)
                    except User.DoesNotExist:
                         return Response(
                            {'error': 'User not found with this phone number'},
                            status=status.HTTP_404_NOT_FOUND
                        )
                else:
                    logger.warning(f"Invalid Firebase Token received for {phone_number}")
                    return Response(
                        {'error': 'Invalid Firebase Token'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Legacy OTP Flow
            try:
                otp_verification = OTPVerification.objects.get(
                    phone_number=phone_number,
                    is_verified=False
                )
            except OTPVerification.DoesNotExist:
                return Response(
                    {'error': 'Invalid OTP request'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if OTP is expired
            if otp_verification.is_expired():
                return Response(
                    {'error': 'OTP has expired'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check attempts
            if not otp_verification.can_retry():
                return Response(
                    {'error': 'Maximum OTP attempts exceeded'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Verify OTP
            # Use direct comparison now
            if str(otp_verification.otp_code) == str(otp_code):
                # Mark as verified
                otp_verification.is_verified = True
                otp_verification.save()

                # Activate user and mark phone as verified
                user = otp_verification.user
                user.is_active = True
                user.is_phone_verified = True
                user.save()

                # Create or activate RetailerProfile for retailer users
                if user.user_type == 'retailer':
                    profile, created = RetailerProfile.objects.get_or_create(
                        user=user,
                        defaults={
                            'shop_name': f"{user.first_name or user.username}'s Shop",
                            'shop_description': '',
                            'business_type': 'general',
                            'address_line1': '',
                            'city': '',
                            'state': '',
                            'pincode': '000000',
                            'contact_phone': user.phone_number or '',
                            'is_active': True,
                        }
                    )
                    # Activate existing profile on phone verification
                    if not created and not profile.is_active:
                        profile.is_active = True
                        profile.save()
                        logger.info(f"Activated RetailerProfile for user: {user.username}")
                    elif created:
                        # Create default operating hours for new profile
                        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                        for day in days:
                            RetailerOperatingHours.objects.create(
                                retailer=profile,
                                day_of_week=day,
                                is_open=True,
                                opening_time='09:00',
                                closing_time='21:00'
                            )
                        logger.info(f"Created RetailerProfile for user: {user.username}")

                # Generate JWT tokens
                refresh = RefreshToken.for_user(user)

                response_data = {
                    'message': 'OTP verified successfully',
                    'user': UserProfileSerializer(user).data,
                    'tokens': {
                        'access': str(refresh.access_token),
                        'refresh': str(refresh),
                    }
                }

                logger.info(f"Customer OTP verified: {user.username}")
                return Response(response_data, status=status.HTTP_200_OK)
            else:
                # Increment attempts
                otp_verification.attempts += 1
                otp_verification.save()

                return Response(
                    {'error': 'Invalid OTP'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in OTP verification: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_profile(request):
    """
    Get user profile
    """
    try:
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_profile(request):
    """
    Update user profile
    """
    try:
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=request.method == 'PATCH'
        )

        if serializer.is_valid():
            user = serializer.save()
            logger.info(f"Profile updated: {user.username}")
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    """
    Change user password
    """
    try:
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})

        if serializer.is_valid():
            user = request.user
            user.set_password(serializer.validated_data['new_password'])
            user.save()

            logger.info(f"Password changed: {user.username}")
            return Response(
                {'message': 'Password changed successfully'},
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error changing password: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def logout(request):
    """
    Logout user by blacklisting refresh token
    """
    try:
        refresh_token = request.data.get('refresh_token')

        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()

        logger.info(f"User logged out: {request.user.username}")
        return Response(
            {'message': 'Logout successful'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error in logout: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPThrottle])
def resend_otp(request):
    """
    Resend OTP for both Signup and Login scenarios
    """
    try:
        serializer = OTPRequestSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']

            # 1. Verify user exists
            try:
                user = User.objects.get(phone_number=phone_number, user_type='customer')
            except User.DoesNotExist:
                return Response(
                    {'error': 'No account found with this phone number.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 2. Rate limiting for Resend specifically (Separate from Request OTP)
            cache_key = f"resend_otp_limit_{phone_number}"
            resend_count = cache.get(cache_key, 0)

            if resend_count >= 3: # Limit to 3 resends per hour
                return Response(
                    {'error': 'Too many resend attempts. Please wait 15 mins.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # 3. Generate new OTP
            otp_code, secret_key = generate_otp()

            # 4. Update or Create OTP Verification record
            # We delete the old ones so only the latest OTP is valid
            OTPVerification.objects.filter(user=user).delete()

            OTPVerification.objects.create(
                user=user,
                phone_number=phone_number,
                otp_code=otp_code,
                secret_key=secret_key,
                expires_at=timezone.now() + timezone.timedelta(seconds=settings.OTP_EXPIRY_TIME)
            )

            # 5. Send SMS
            sms_sent = send_sms_otp(phone_number, otp_code)

            if sms_sent:
                # Update resend count in cache
                cache.set(cache_key, resend_count + 1, 900)

                logger.info(f"OTP Resent to {phone_number}")
                return Response({
                    'message': 'OTP resent successfully',
                    'phone_number': phone_number,
                    'expires_in': settings.OTP_EXPIRY_TIME
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {'error': 'Failed to send SMS. Please try again later.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in resend_otp: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def register_device(request):
    """
    Register or update an FCM device token for the authenticated user.
    """
    try:
        token = request.data.get('registration_id')
        device_type = request.data.get('type', 'android')
        name = request.data.get('name', 'unnamed')

        if not token:
            return Response(
                {'error': 'registration_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Register or update device
        device, created = FCMDevice.objects.get_or_create(
            registration_id=token,
            defaults={
                'user': request.user,
                'type': device_type,
                'name': name,
                'active': True
            }
        )

        if not created:
            device.user = request.user
            device.type = device_type
            device.name = name
            device.active = True
            device.save()

        logger.info(f"FCM Device registered for user {request.user.username}: {token}")
        return Response(
            {'message': 'Device registered successfully'},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Error registering FCM device: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPThrottle])
def forgot_password(request):
    """
    Request password reset OTP
    """
    try:
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            user = User.objects.get(phone_number=phone_number)

            # Generate OTP
            otp_code, secret_key = generate_otp()

            # Update/Create verification record
            OTPVerification.objects.filter(user=user).delete()
            
            OTPVerification.objects.create(
                user=user,
                phone_number=phone_number,
                otp_code=otp_code,
                secret_key=secret_key,
                expires_at=timezone.now() + timezone.timedelta(seconds=settings.OTP_EXPIRY_TIME)
            )

            # Send OTP
            sms_sent = send_sms_otp(phone_number, otp_code)

            if sms_sent:
                logger.info(f"Password reset OTP sent to {phone_number}")
                return Response({
                    'message': 'OTP sent successfully',
                    'phone_number': phone_number,
                    'expires_in': settings.OTP_EXPIRY_TIME
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {'error': 'Failed to send OTP'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in forgot_password: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPThrottle])
def reset_password(request):
    """
    Verify OTP and reset password
    """
    try:
        serializer = ResetPasswordConfirmSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            otp_code = serializer.validated_data.get('otp_code')
            firebase_token = serializer.validated_data.get('firebase_token')
            new_password = serializer.validated_data['new_password']

            # Firebase Token Verification Flow
            if firebase_token:
                decoded_token = verify_firebase_id_token(firebase_token)
                if decoded_token:
                    # Token valid, check if it matches the phone number (optional but recommended)
                    # For now we assume the client verified the phone number
                    
                    try:
                        user = User.objects.get(phone_number=phone_number)
                         # Change password
                        user.set_password(new_password)
                        user.save()

                        logger.info(f"Password reset successful via Firebase for: {phone_number}")
                        return Response(
                            {'message': 'Password reset successfully. Please login with new password.'},
                            status=status.HTTP_200_OK
                        )
                    except User.DoesNotExist:
                         return Response(
                            {'error': 'User not found with this phone number'},
                            status=status.HTTP_404_NOT_FOUND
                        )
                else:
                    return Response(
                        {'error': 'Invalid Firebase Token'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Legacy OTP Flow
            # Verify OTP
            try:
                otp_verification = OTPVerification.objects.get(
                    phone_number=phone_number,
                    is_verified=False
                )
            except OTPVerification.DoesNotExist:
                return Response(
                    {'error': 'Invalid or expired OTP request'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if otp_verification.is_expired():
                return Response(
                    {'error': 'OTP has expired'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not verify_otp_helper(otp_verification.secret_key, otp_code):
                otp_verification.attempts += 1
                otp_verification.save()
                return Response(
                    {'error': 'Invalid OTP'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # OTP Valid, change password
            user = otp_verification.user
            user.set_password(new_password)
            user.save()

            # Cleanup OTP
            otp_verification.delete()

            logger.info(f"Password reset successful for: {phone_number}")
            return Response(
                {'message': 'Password reset successfully. Please login with new password.'},
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in reset_password: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPThrottle])
def forgot_password_email(request):
    """
    Request password reset OTP via email
    """
    try:
        serializer = ForgotPasswordEmailSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.get(email=email)

            # Generate OTP
            otp_code, secret_key = generate_otp()

            # Update/Create verification record
            EmailOTPVerification.objects.filter(user=user).delete()
            
            EmailOTPVerification.objects.create(
                user=user,
                email=email,
                otp_code=otp_code,
                secret_key=secret_key,
                expires_at=timezone.now() + timezone.timedelta(seconds=settings.OTP_EXPIRY_TIME)
            )

            # Send OTP
            email_sent = send_email_otp(email, otp_code)

            if email_sent:
                logger.info(f"Password reset OTP sent to {email}")
                return Response({
                    'message': 'OTP sent successfully to email',
                    'email': email,
                    'expires_in': settings.OTP_EXPIRY_TIME
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {'error': 'Failed to send OTP email'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in forgot_password_email: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@throttle_classes([OTPThrottle])
def reset_password_email(request):
    """
    Verify Email OTP and reset password
    """
    try:
        serializer = ResetPasswordEmailConfirmSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp_code = serializer.validated_data.get('otp_code')
            new_password = serializer.validated_data['new_password']

            # Verify OTP
            try:
                otp_verification = EmailOTPVerification.objects.get(
                    email=email,
                    is_verified=False
                )
            except EmailOTPVerification.DoesNotExist:
                return Response(
                    {'error': 'Invalid or expired OTP request'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if otp_verification.is_expired():
                return Response(
                    {'error': 'OTP has expired'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Using direct string match for email OTPs without secret key legacy
            # (which verify_otp_helper falls back to if expected_otp is not passed, 
            #  but let's do a direct verification here to ensure it uses the db's otp_code strictly)
            if str(otp_verification.otp_code) != str(otp_code):
                otp_verification.attempts += 1
                otp_verification.save()
                return Response(
                    {'error': 'Invalid OTP'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # OTP Valid, change password
            user = otp_verification.user
            user.set_password(new_password)
            user.save()

            # Cleanup OTP
            otp_verification.delete()

            logger.info(f"Password reset successful for email: {email}")
            return Response(
                {'message': 'Password reset successfully. Please login with your new password.'},
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in reset_password_email: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def verify_email_otp(request):
    """
    Verify email OTP for signup
    """
    try:
        serializer = EmailVerifySerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp_code = serializer.validated_data['otp_code']
            
            try:
                user = User.objects.get(email=email)
                otp_ver = EmailOTPVerification.objects.filter(
                    user=user, 
                    email=email, 
                    otp_code=otp_code,
                    is_verified=False
                ).latest('created_at')
                
                # Check expiry
                if otp_ver.is_expired():
                    return Response({'error': 'OTP has expired'}, status=status.HTTP_400_BAD_REQUEST)
                
                otp_ver.is_verified = True
                otp_ver.save()
                
                user.is_email_verified = True
                user.save()
                
                logger.info(f"Email verified for user: {user.username}")
                return Response({'message': 'Email verified successfully'}, status=status.HTTP_200_OK)
                
            except (User.DoesNotExist, EmailOTPVerification.DoesNotExist):
                return Response({'error': 'Invalid email or OTP'}, status=status.HTTP_400_BAD_REQUEST)
                
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error in verify_email_otp: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def resend_email_otp(request):
    """
    Resend email OTP
    """
    try:
        email = request.data.get('email')
        if not email:
            return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            user = User.objects.get(email=email)
            
            # Generate new OTP
            otp_code, secret_key = generate_otp()
            
            # Use same pattern as forgot password for consistency
            EmailOTPVerification.objects.filter(user=user).delete()
            EmailOTPVerification.objects.create(
                user=user,
                email=email,
                otp_code=otp_code,
                secret_key=secret_key,
                expires_at=timezone.now() + timezone.timedelta(seconds=settings.OTP_EXPIRY_TIME)
            )
            
            send_email_otp(email, otp_code)
            logger.info(f"Email OTP resent to {email}")
            return Response({'message': 'OTP resent successfully'}, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error in resend_email_otp: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
