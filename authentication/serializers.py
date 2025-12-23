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
    
    phone_number = serializers.CharField(max_length=15, required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm', 'user_type', 'phone_number']
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Passwords don't match"})
        
        phone_number = attrs.get('phone_number')
        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            raise serializers.ValidationError({"phone_number": "Phone number already registered"})
            
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
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
    otp_code = serializers.CharField(max_length=6)
    name = serializers.CharField(max_length=150, required=False)
    
    def validate_otp_code(self, value):
        if not value.isdigit() or len(value) != 6:
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
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 
                 'phone_number', 'user_type', 'is_phone_verified', 'created_at']
        read_only_fields = ['id', 'username', 'user_type', 'is_phone_verified', 'created_at']


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
