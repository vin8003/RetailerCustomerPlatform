import os
import sys
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from retailers.models import RetailerProfile, RetailerCategory, RetailerCategoryMapping
from retailers.serializers import RetailerProfileUpdateSerializer

# Get or create a profile for testing
# We'll just take the first one if it exists, otherwise create a dummy
profile = RetailerProfile.objects.first()

if not profile:
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user, _ = User.objects.get_or_create(username='test_retailer', email='test@test.com', user_type='retailer')
    profile, _ = RetailerProfile.objects.get_or_create(user=user, shop_name='Test Shop', pincode='123456')

print(f"Testing with Retailer: {profile.shop_name}")

# Get categories
categories = RetailerCategory.objects.all()[:2]
cat_ids = [cat.id for cat in categories]
print(f"Selected Category IDs to add: {cat_ids}")

# Test Data
data = {
    'categories': cat_ids
}

# Update
serializer = RetailerProfileUpdateSerializer(profile, data=data, partial=True)
if serializer.is_valid():
    serializer.save()
    print("Update successful")
    
    # Verify mappings
    mappings = RetailerCategoryMapping.objects.filter(retailer=profile)
    print(f"Mapped categories count: {mappings.count()}")
    for m in mappings:
        print(f"- {m.category.name}")
else:
    print("Errors:")
    print(serializer.errors)
