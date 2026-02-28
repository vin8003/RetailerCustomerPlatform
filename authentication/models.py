from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """
    Custom user model that extends Django's AbstractUser
    """
    USER_TYPE_CHOICES = [
        ('retailer', 'Retailer'),
        ('customer', 'Customer'),
    ]
    
    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default='customer'
    )
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    is_phone_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user_type']),
            models.Index(fields=['phone_number']),
        ]

    def __str__(self):
        return f"{self.username} ({self.user_type})"


class OTPVerification(models.Model):
    """
    Model to store OTP verification data for phone authentication
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=15)
    otp_code = models.CharField(max_length=6)
    secret_key = models.CharField(max_length=32)
    is_verified = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = 'otp_verification'
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['expires_at']),
        ]
    
    def is_expired(self):
        """Check if OTP has expired"""
        return timezone.now() > self.expires_at
    
    def can_retry(self):
        """Check if user can retry OTP verification"""
        from django.conf import settings
        return self.attempts < settings.OTP_MAX_ATTEMPTS
    
    def __str__(self):
        return f"OTP for {self.phone_number}"


class UserSession(models.Model):
    """
    Model to track user sessions for security purposes
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_token = models.CharField(max_length=255, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_session'
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['session_token']),
        ]
    
    def __str__(self):
        return f"Session for {self.user.username}"


class EmailOTPVerification(models.Model):
    """
    Model to store OTP verification data for email authentication/password resetting
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    email = models.EmailField()
    otp_code = models.CharField(max_length=6)
    secret_key = models.CharField(max_length=32)
    is_verified = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = 'email_otp_verification'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['expires_at']),
        ]
    
    def is_expired(self):
        """Check if OTP has expired"""
        return timezone.now() > self.expires_at
    
    def can_retry(self):
        """Check if user can retry OTP verification"""
        from django.conf import settings
        return self.attempts < settings.OTP_MAX_ATTEMPTS
    
    def __str__(self):
        return f"Email OTP for {self.email}"
