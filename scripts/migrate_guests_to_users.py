import os
import django
import secrets
from decimal import Decimal
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from django.contrib.auth import get_user_model
from orders.models import Order
from retailers.models import RetailerCustomerMapping
from django.utils import timezone

User = get_user_model()

def migrate_guests():
    print("Starting Guest to Unified User Migration...")
    
    # Find all orders that have guest_mobile but no User object linked
    orders_to_migrate = Order.objects.filter(customer__isnull=True).exclude(guest_mobile__isnull=True).exclude(guest_mobile='')
    
    count = 0
    total = orders_to_migrate.count()
    print(f"Found {total} orders to migrate.")
    
    for order in orders_to_migrate:
        mobile = order.guest_mobile
        name = order.guest_name or "Walk-in Guest"
        
        # 1. Find or create the Shadow User (Normalizing phone to match variations)
        clean_mobile = ''.join(filter(str.isdigit, mobile))
        last_10 = clean_mobile[-10:] if len(clean_mobile) >= 10 else clean_mobile
        
        user_query = User.objects.filter(username__endswith=last_10) | User.objects.filter(phone_number__endswith=last_10)
        user = user_query.first()
        
        if not user:
            user = User.objects.create(
                username=mobile,
                phone_number=mobile,
                first_name=name,
                registration_status='shadow',
                is_phone_verified=False
            )
            user.set_password(secrets.token_urlsafe(12))
            user.save()
            print(f"Created Shadow User for {mobile}")
        
        # 2. Link the Order to the User
        order.customer = user
        order.save()
        
        # 3. Create/Update the RetailerCustomerMapping
        mapping, created = RetailerCustomerMapping.objects.get_or_create(
            retailer=order.retailer,
            customer=user
        )
        
        if not mapping.nickname:
            mapping.nickname = order.guest_name
            
        mapping.total_orders = Order.objects.filter(retailer=order.retailer, customer=user).count()
        mapping.total_spent = sum(o.total_amount for o in Order.objects.filter(retailer=order.retailer, customer=user))
        mapping.customer_type = 'walk_in' if user.registration_status == 'shadow' else 'hybrid'
        mapping.save()
        
        count += 1
        if count % 10 == 0:
            print(f"Progress: {count}/{total}")

    print(f"Migration Complete! {count} orders linked.")

if __name__ == "__main__":
    migrate_guests()
