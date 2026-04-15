from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, OTPVerification


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration
    """
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    # We define these explicitly to remove the default UniqueValidators, 
    # so we can handle "Shadow User" collisions manually in validate()
    username = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=15, required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm', 'user_type', 'phone_number']
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Passwords don't match"})
        
        username = attrs.get('username')
        phone_number = attrs.get('phone_number')

        # Check for Username collisions
        if username:
            existing_user = User.objects.filter(username=username).first()
            if existing_user and existing_user.registration_status != 'shadow':
                raise serializers.ValidationError({"username": "A user with that username already exists."})

        # Check for Phone Number collisions
        if phone_number:
            # Normalize phone for consistent lookup (last 10 digits)
            clean_phone = ''.join(filter(str.isdigit, phone_number))
            last_10 = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
            
            existing_user = User.objects.filter(phone_number__endswith=last_10).first()
            if existing_user and existing_user.registration_status != 'shadow':
                raise serializers.ValidationError({"phone_number": "Phone number already registered"})
            
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        username = validated_data.get('username')
        phone_number = validated_data.get('phone_number')
        
        # Check for existing shadow user to "claim" (Match by normalized phone OR username)
        existing_user = None
        
        if phone_number:
            clean_phone = ''.join(filter(str.isdigit, phone_number))
            last_10 = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
            existing_user = User.objects.filter(phone_number__endswith=last_10, registration_status='shadow').first()
            
        if not existing_user and username:
            existing_user = User.objects.filter(username=username, registration_status='shadow').first()

        if existing_user:
            # Update existing shadow user to full registered user
            for attr, value in validated_data.items():
                if attr == 'password':
                    existing_user.set_password(value)
                else:
                    setattr(existing_user, attr, value)
            
            existing_user.registration_status = 'registered'
            existing_user.save()
            return existing_user
        
        # Otherwise create a new user
        user = User.objects.create_user(**validated_data)
        return user


class UserLoginSerializer(serializers.Serializer):
    """
    Serializer for user login
    """
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        
        if username and password:
            # Try to authenticate with username/email
            user = authenticate(username=username, password=password)
            
            if not user:
                # Try to authenticate with email
                try:
                    user_obj = User.objects.get(email=username)
                    user = authenticate(username=user_obj.username, password=password)
                except User.DoesNotExist:
                    # Try to authenticate with phone_number
                    try:
                        user_obj = User.objects.get(phone_number=username)
                        user = authenticate(username=user_obj.username, password=password)
                    except User.DoesNotExist:
                        pass
            
            if not user:
                raise serializers.ValidationError('Invalid credentials')
            
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled')
            
            attrs['user'] = user
            return attrs
        
        raise serializers.ValidationError('Must provide username and password')


class OTPRequestSerializer(serializers.Serializer):
    """
    Serializer for OTP request
    """
    phone_number = serializers.CharField(max_length=15)
    
    def validate_phone_number(self, value):
        # Basic phone number validation
        if not value.startswith('+'):
            raise serializers.ValidationError("Phone number must start with country code (+)")
        
        # Remove spaces and special characters
        cleaned_number = ''.join(filter(str.isdigit, value[1:]))
        if len(cleaned_number) < 10:
            raise serializers.ValidationError("Invalid phone number")
        
        return value


class OTPVerificationSerializer(serializers.Serializer):
    """
    Serializer for OTP verification
    """
    phone_number = serializers.CharField(max_length=15)
    otp_code = serializers.CharField(max_length=6, required=False)
    firebase_token = serializers.CharField(required=False)
    name = serializers.CharField(max_length=150, required=False)
    
    def validate(self, attrs):
        otp_code = attrs.get('otp_code')
        firebase_token = attrs.get('firebase_token')

        if not otp_code and not firebase_token:
            raise serializers.ValidationError("Either otp_code or firebase_token must be provided.")
            
        return attrs

    def validate_otp_code(self, value):
        if value and (not value.isdigit() or len(value) != 6):
            raise serializers.ValidationError("OTP must be 6 digits")
        return value


class RequestPhoneVerificationSerializer(serializers.Serializer):
    """
    Serializer for authenticated user requesting phone verification
    """
    pass  # No args needed as we use request.user.phone_number


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for user profile
    """
    shop_name = serializers.SerializerMethodField()
    shop_image = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 
                 'phone_number', 'user_type', 'is_phone_verified', 'created_at',
                 'shop_name', 'shop_image']
        read_only_fields = ['id', 'username', 'user_type', 'is_phone_verified', 'created_at']

    def get_shop_name(self, obj):
        if obj.user_type == 'retailer' and hasattr(obj, 'retailer_profile'):
            return obj.retailer_profile.shop_name
        return None

    def get_shop_image(self, obj):
        if obj.user_type == 'retailer' and hasattr(obj, 'retailer_profile') and obj.retailer_profile.shop_image:
            return obj.retailer_profile.shop_image.url
        return None


class TokenSerializer(serializers.Serializer):
    """
    Serializer for token response
    """
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    user = UserProfileSerializer()
    token_type = serializers.CharField(default='Bearer')
    expires_in = serializers.IntegerField()
    
    def create(self, validated_data):
        user = validated_data['user']
        refresh = RefreshToken.for_user(user)
        
        return {
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh),
            'user': user,
            'token_type': 'Bearer',
            'expires_in': 1800,  # 30 minutes
        }


class PasswordChangeSerializer(serializers.Serializer):
    """
    Serializer for password change
    """
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError("New passwords don't match")
        return attrs
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect")
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    """
    Serializer for password reset request (OTP generation)
    """
    phone_number = serializers.CharField(max_length=15)

    def validate_phone_number(self, value):
        # reuse logic or just simple check
        from .utils import clean_phone_number
        cleaned = clean_phone_number(value)
        if not User.objects.filter(phone_number=cleaned).exists():
            raise serializers.ValidationError("No account found with this phone number.")
        return cleaned


class ResetPasswordConfirmSerializer(serializers.Serializer):
    """
    Serializer for password reset confirmation (OTP verification + new password)
    """
    phone_number = serializers.CharField(max_length=15)
    otp_code = serializers.CharField(max_length=6, required=False)
    firebase_token = serializers.CharField(required=False)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"new_password": "Passwords don't match"})
            
        if not attrs.get('otp_code') and not attrs.get('firebase_token'):
            raise serializers.ValidationError("Either otp_code or firebase_token must be provided.")
            
        return attrs


class ForgotPasswordEmailSerializer(serializers.Serializer):
    """
    Serializer for email password reset request (OTP generation)
    """
    email = serializers.EmailField()

    def validate_email(self, value):
        from .models import User
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("No account found with this email.")
        return value


class ResetPasswordEmailConfirmSerializer(serializers.Serializer):
    """
    Serializer for password reset confirmation via email (OTP verification + new password)
    """
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"new_password": "Passwords don't match"})
        return attrs


class EmailVerifySerializer(serializers.Serializer):
    """
    Serializer for email verification (OTP verification)
    """
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)

