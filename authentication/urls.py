from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from . import views

urlpatterns = [
    # Retailer authentication
    path('retailer/signup/', views.retailer_signup, name='retailer_signup'),
    path('retailer/login/', views.retailer_login, name='retailer_login'),

    # Customer authentication
    path('customer/signup/', views.customer_signup, name='customer_signup'),
    path('customer/login/', views.customer_login, name='customer_login'),
    path('customer/verify-otp/', views.verify_otp, name='verify_otp'),
    path('customer/resend-otp/', views.resend_otp, name='resend_otp'),
    path('customer/request-verification/', views.request_phone_verification, name='request_phone_verification'),

    # Common authentication
    path('profile/', views.get_profile, name='get_profile'),
    path('profile/update/', views.update_profile, name='update_profile'),
    path('change-password/', views.change_password, name='change_password'),
    path('logout/', views.logout, name='logout'),

    # JWT token management
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('device/register/', views.register_device, name='register_device'),

    # Password Reset
    path('password/forgot/', views.forgot_password, name='forgot_password'),
    path('password/reset/', views.reset_password, name='reset_password'),
    path('password/email/forgot/', views.forgot_password_email, name='forgot_password_email'),
    path('password/email/reset/', views.reset_password_email, name='reset_password_email'),
]
