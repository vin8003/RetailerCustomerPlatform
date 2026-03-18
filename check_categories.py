import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from retailers.models import RetailerCategory

categories = RetailerCategory.objects.all()
print(f"Total categories: {categories.count()}")
for cat in categories:
    print(f"- {cat.name} (Active: {cat.is_active})")
