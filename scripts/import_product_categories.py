import csv
import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from products.models import MasterProduct, Product, ProductCategory

def import_data(csv_file_path):
    print(f"Reading from {csv_file_path}...")
    
    with open(csv_file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        count = 0
        updated_master = 0
        updated_products = 0
        
        for row in reader:
            barcode = row.get('barcode', '').strip()
            primary_cat_name = row.get('primary category', '').strip()
            sub_cat_name = row.get('sub category', '').strip() or row.get('original_category', '').strip()
            
            # The CSV header says "product group" but let's check exact key from head call earlier
            # output was: barcode,brand,variant_name,size,unit,original_category,primary category,sub category,product group
            product_group = row.get('product group', '').strip()

            if not barcode:
                continue

            # 1. Handle Categories
            primary_cat = None
            if primary_cat_name:
                primary_cat, created = ProductCategory.objects.get_or_create(
                    name=primary_cat_name,
                    defaults={'parent': None}
                )
            
            sub_cat = None
            if sub_cat_name:
                sub_cat, created = ProductCategory.objects.get_or_create(
                    name=sub_cat_name,
                    defaults={'parent': primary_cat}
                )
                # If existing subcat has no parent but we now know it, update it? 
                # Ideally yes, but let's trust get_or_create logic for now or update if needed.
                if sub_cat.parent is None and primary_cat:
                    sub_cat.parent = primary_cat
                    sub_cat.save()

            target_category = sub_cat if sub_cat else primary_cat

            # 2. Update MasterProduct
            try:
                master_products = MasterProduct.objects.filter(barcode=barcode)
                for mp in master_products:
                    updated = False
                    if target_category and mp.category != target_category:
                        mp.category = target_category
                        updated = True
                    if product_group and mp.product_group != product_group:
                        mp.product_group = product_group
                        updated = True
                    
                    if updated:
                        mp.save()
                        updated_master += 1
            except Exception as e:
                print(f"Error updating MasterProduct {barcode}: {e}")

            # 3. Update Retailer Products
            try:
                products = Product.objects.filter(barcode=barcode)
                for p in products:
                    updated = False
                    if target_category and p.category != target_category:
                        p.category = target_category
                        updated = True
                    if product_group and p.product_group != product_group:
                        p.product_group = product_group
                        updated = True
                    
                    if updated:
                        p.save()
                        updated_products += 1
            except Exception as e:
                print(f"Error updating Product {barcode}: {e}")

            count += 1
            if count % 100 == 0:
                print(f"Processed {count} rows...")

    print("Import completed.")
    print(f"Total Rows: {count}")
    print(f"Updated MasterProducts: {updated_master}")
    print(f"Updated Products: {updated_products}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = input("Enter the path to the CSV file: ").strip()
    
    if csv_path and os.path.exists(csv_path):
        import_data(csv_path)
    else:
        print(f"File not found or invalid path: {csv_path}")
