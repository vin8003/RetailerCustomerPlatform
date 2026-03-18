import os
import sys
import django

# Add the parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from retailers.models import RetailerCategory

categories_to_ensure = [
    {'name': 'Grocery', 'icon': 'shopping-basket'},
    {'name': 'Food', 'icon': 'utensils'},
    {'name': 'Others', 'icon': 'ellipsis-h'}
]

for cat_data in categories_to_ensure:
    category, created = RetailerCategory.objects.get_or_create(
        name=cat_data['name'],
        defaults={'icon': cat_data['icon'], 'is_active': True}
    )
    if created:
        print(f"Created category: {cat_data['name']}")
    else:
        print(f"Category already exists: {cat_data['name']}")

print("Category population complete.")
