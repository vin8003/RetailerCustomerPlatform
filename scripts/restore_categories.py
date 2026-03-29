import os
import django
import glob
import pandas as pd

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from products.models import Product, ProductCategory

def restore_categories():
    print("Starting category restoration...")
    
    # 2. Iterate through all uploaded CSVs in media/uploads/productupload
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'media', 'uploads', 'productupload')
    
    csv_files = glob.glob(os.path.join(upload_dir, '**', '*.csv'), recursive=True)
    excel_files = glob.glob(os.path.join(upload_dir, '**', '*.xlsx'), recursive=True)
    all_files = csv_files + excel_files
    
    print(f"Found {len(all_files)} upload files to parse.")
    
    restored_count = 0
    not_found_count = 0
    
    for file_path in all_files:
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
                
            # Need to match products. We assume 'barcode' or 'name' matches.
            # Usually the upload has matching columns. Let's normalize column names.
            df.columns = df.columns.astype(str).str.lower().str.strip()
            
            # The bulk upload script expects 'category' column.
            if 'category' not in df.columns:
                continue
                
            for _, row in df.iterrows():
                cat_name = str(row.get('category', '')).strip()
                if not cat_name or pd.isna(row.get('category')):
                    continue
                    
                barcode = str(row.get('barcode', '')).strip()
                name = str(row.get('name', '')).strip()
                
                # Fetch category object
                category, _ = ProductCategory.objects.get_or_create(name=cat_name, retailer=None, defaults={'is_active': True})
                
                # Find matching products
                prods = None
                if barcode and barcode != 'nan':
                    prods = Product.objects.filter(barcode=barcode)
                elif name and name != 'nan':
                    prods = Product.objects.filter(name=name)
                    
                if prods and prods.exists():
                    updated = prods.update(category=category)
                    restored_count += updated
                else:
                    not_found_count += 1
                    
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
    print(f"Restoration complete! Categories reassigned: {restored_count}. Products not found: {not_found_count}")

if __name__ == '__main__':
    restore_categories()
