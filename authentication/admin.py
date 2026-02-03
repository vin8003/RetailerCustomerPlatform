from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, OTPVerification, UserSession, EmailOTPVerification


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """
    Admin configuration for custom User model
    """
    list_display = ['username', 'email', 'phone_number', 'user_type', 'is_phone_verified', 'is_email_verified', 'is_active', 'created_at']
    list_filter = ['user_type', 'is_active', 'is_phone_verified', 'is_email_verified', 'created_at']
    search_fields = ['username', 'email', 'phone_number', 'first_name', 'last_name']
    ordering = ['-created_at']
    
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('user_type', 'phone_number', 'is_phone_verified', 'is_email_verified')
        }),
    )


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    """
    Admin configuration for OTP verification
    """
    list_display = ['phone_number', 'user', 'is_verified', 'attempts', 'created_at', 'expires_at']
    list_filter = ['is_verified', 'created_at', 'expires_at']
    search_fields = ['phone_number', 'user__username']
    ordering = ['-created_at']
    readonly_fields = ['otp_code', 'secret_key']


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    """
    Admin configuration for user sessions
    """
    list_display = ['user', 'ip_address', 'is_active', 'created_at', 'last_activity']
    list_filter = ['is_active', 'created_at', 'last_activity']
    search_fields = ['user__username', 'ip_address']
    ordering = ['-last_activity']
    readonly_fields = ['session_token']


@admin.register(EmailOTPVerification)
class EmailOTPVerificationAdmin(admin.ModelAdmin):
    """
    Admin configuration for email OTP verification
    """
    list_display = ['email', 'purpose', 'user', 'is_verified', 'attempts', 'created_at', 'expires_at']
    list_filter = ['purpose', 'is_verified', 'created_at', 'expires_at']
    search_fields = ['email', 'user__username']
    ordering = ['-created_at']
    readonly_fields = ['otp_code', 'secret_key']
