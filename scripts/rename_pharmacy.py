import os
import sys
import django

# Add the parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from retailers.models import RetailerCategory

try:
    category = RetailerCategory.objects.get(name='Pharmacy')
    category.name = 'Customize Gift'
    category.icon = 'gift'  # Update icon to gift
    category.save()
    print("Renamed Pharmacy to Customize Gift")
except RetailerCategory.DoesNotExist:
    # If Pharmacy doesn't exist, create Customize Gift if missing
    cat, created = RetailerCategory.objects.get_or_create(
        name='Customize Gift',
        defaults={'icon': 'gift', 'is_active': True}
    )
    if created:
         print("Created Customize Gift category")
    else:
         print("Customize Gift already exists")

print("Backend category update complete.")
