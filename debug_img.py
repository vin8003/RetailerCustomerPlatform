import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ordering_platform.settings")
django.setup()
from products.models import Product
from products.tests.factories import ProductFactory

p = Product.objects.all().first()
print(f"Product image: {p.image}")
print(f"Product image bool: {bool(p.image)}")
try:
    print(f"Product image url: {p.image.url}")
except Exception as e:
    print(f"Error accessing image url: {e}")
