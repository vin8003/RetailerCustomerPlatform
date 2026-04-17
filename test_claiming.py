import os
import django
import sys
import pytest

# Setup Django environment
sys.path.append(r'C:\Users\user\Desktop\online_files\ordereasy_140226\RetailerCustomerPlatform')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from authentication.models import User
from authentication.serializers import UserRegistrationSerializer

@pytest.mark.django_db
def test_account_claiming():
    phone = "+917777777777"
    # 1. Create Shadow User
    User.objects.filter(phone_number__endswith="7777777777").delete()
    u = User.objects.create(
        username='test_walkin_77', 
        phone_number=phone, 
        registration_status='shadow'
    )
    print(f'Created Shadow User ID: {u.id}, Phone: {u.phone_number}')

    # 2. Simulate App Signup with same phone (different format)
    data = {
        'username': 'rahul_app',
        'phone_number': '7777777777', # No +91
        'password': 'Password@123',
        'password_confirm': 'Password@123',
        'user_type': 'customer',
        'email': 'rahul_77@example.com'
    }
    
    serializer = UserRegistrationSerializer(data=data)
    if serializer.is_valid():
        newUser = serializer.save()
        print(f'Claimed User ID: {newUser.id}, Status: {newUser.registration_status}, Username: {newUser.username}')
        if u.id == newUser.id:
            print("SUCCESS: Existing user account was claimed/converted!")
        else:
            print("FAILURE: New user was created instead of claiming.")
    else:
        print(f'Errors: {serializer.errors}')

if __name__ == "__main__":
    test_account_claiming()
