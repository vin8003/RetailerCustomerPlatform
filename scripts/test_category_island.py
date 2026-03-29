import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from retailers.models import RetailerProfile
from products.models import ProductCategory, Product
from django.contrib.auth import get_user_model
from django.test.client import RequestFactory
from django.contrib.auth.models import AnonymousUser

User = get_user_model()

print("--- Starting global category fallback test ---")
user1, _ = User.objects.get_or_create(username='test_retailer1', user_type='retailer')
retailer1, _ = RetailerProfile.objects.get_or_create(user=user1, shop_name='Shop 1')

# Clean existing test cats
ProductCategory.objects.all().delete()

# Create a global category
global_cat = ProductCategory.objects.create(name='Global Dairy', retailer=None)

# Let retailer1 use this category in a product
prod1 = Product.objects.create(name='Milk', retail_price=20, price=20, quantity=10, retailer=retailer1, category=global_cat)

print("Checking if retailer can see the global category natively...")
from products.views import get_product_categories
factory = RequestFactory()
request = factory.get('/products/categories/')
request.user = user1
response = get_product_categories(request)
categories_in_response = [c['name'] for c in response.data]
print(f"Categories returned for Retailer 1: {categories_in_response}")
assert 'Global Dairy' in categories_in_response, "Global category used by retailer should appear!"

print("Checking cloning logic during update...")
from products.views import update_product_category
request = factory.patch(f'/products/categories/{global_cat.id}/update/', {'description': 'New isolated description'})
request.user = user1
response = update_product_category(request, global_cat.id)
assert response.status_code == 200, f"Failed: {response.data}"
print(f"Updated category name: {response.data['name']}, Retailer ID: {response.data['retailer_id']}")
assert response.data['retailer_id'] == retailer1.id, "Category should have been cloned and assigned to retailer!"

# Verify old global category still exists
assert ProductCategory.objects.filter(id=global_cat.id).exists(), "Original global category should not be deleted!"

# Clean up
Product.objects.all().delete()
ProductCategory.objects.all().delete()
print("--- Test finished successfully ---")
