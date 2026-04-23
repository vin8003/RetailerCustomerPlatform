import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from products.models import Product, ProductBatch
from django.db import transaction

def migrate_products_to_batches():
    products = Product.objects.all()
    count = 0
    
    with transaction.atomic():
        for p in products:
            # Check if it already has batches (avoid duplicates if re-run)
            if p.batches.exists():
                print(f"Skipping {p.name} - already has batches.")
                continue
            
            # Create the initial batch from current product state
            ProductBatch.objects.create(
                product=p,
                retailer=p.retailer,
                batch_number="INITIAL-STOCK",
                barcode=p.barcode,
                purchase_price=p.purchase_price,
                price=p.price,
                original_price=p.original_price,
                quantity=p.quantity,
                is_active=True,
                show_on_app=True
            )
            
            # Enable batches for the product
            p.has_batches = True
            p.save()
            count += 1
            if count % 10 == 0:
                print(f"Processed {count} products...")

    print(f"Migration complete. {count} products migrated to batch system.")

if __name__ == "__main__":
    migrate_products_to_batches()
