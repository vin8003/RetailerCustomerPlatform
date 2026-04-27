import os
import django

# Setup Django environment
import sys
project_path = r'c:\Users\user\Desktop\online_files\ordereasy_140226\RetailerCustomerPlatform'
sys.path.append(project_path)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from products.models import Product, ProductBatch
from django.db import transaction

def fix_batch_defaults():
    print("Starting data correction for product batches...")
    
    with transaction.atomic():
        # Find all products that have has_batches=True
        products = Product.objects.filter(has_batches=True)
        count = 0
        total = products.count()
        
        for product in products:
            # Check how many active batches it has
            batch_count = product.batches.filter(is_active=True).count()
            
            # If 0 or 1 batch, we can safely set has_batches=False
            # This restores the 'Simple View' for the retailer
            if batch_count <= 1:
                product.has_batches = False
                product.save()
                
                # If there's exactly one batch, ensure its data matches the master product
                # (though it should already match if synced correctly)
                batch = product.batches.filter(is_active=True).first()
                if batch:
                    # Sync product fields TO the batch to ensure they are identical
                    batch.price = product.price
                    batch.original_price = product.original_price
                    batch.purchase_price = product.purchase_price
                    batch.quantity = product.quantity
                    batch.barcode = product.barcode
                    batch.save()
                
                count += 1
                if count % 100 == 0:
                    print(f"Corrected {count}/{total} products...")

    print(f"Data correction complete! {count} products reverted to 'Simple View' (has_batches=False).")

if __name__ == "__main__":
    fix_batch_defaults()
