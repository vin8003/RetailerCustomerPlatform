import sqlite3
import json
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from products.models import MasterProduct, ProductCategory, ProductBrand
from django.db import transaction
from decimal import Decimal

class Command(BaseCommand):
    help = 'Migrate master product data from local SQLite to the current database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sqlite-path',
            type=str,
            default=os.path.join(settings.BASE_DIR, 'db.sqlite3'),
            help='Path to the source SQLite database'
        )

    def handle(self, *args, **options):
        sqlite_path = options['sqlite_path']
        
        if not os.path.exists(sqlite_path):
            self.stdout.write(self.style.ERROR(f"SQLite file not found at {sqlite_path}"))
            return

        self.stdout.write(f"Connecting to SQLite: {sqlite_path}")
        conn = sqlite_connect(sqlite_path)
        cursor = conn.cursor()

        try:
            # 1. Migrate Categories
            self.migrate_categories(cursor)
            
            # 2. Migrate Brands
            self.migrate_brands(cursor)
            
            # 3. Migrate Master Products
            self.migrate_master_products(cursor)

            self.stdout.write(self.style.SUCCESS("Migration completed successfully!"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Migration failed: {str(e)}"))
            import traceback
            traceback.print_exc()
        finally:
            conn.close()

    def migrate_categories(self, cursor):
        self.stdout.write("Migrating Product Categories...")
        cursor.execute("SELECT id, name, description, icon, is_active, parent_id FROM product_category")
        sqlite_cats = cursor.fetchall()
        
        # 1. Get existing categories in target DB
        target_cats = {cat.name: cat for cat in ProductCategory.objects.all()}
        self.stdout.write(f"  Found {len(target_cats)} existing categories in target DB.")

        # 2. Create missing categories with parent=None first
        to_create = []
        for row in sqlite_cats:
            old_id, name, description, icon, is_active, parent_id = row
            if name not in target_cats:
                to_create.append(ProductCategory(
                    name=name,
                    description=description or '',
                    icon=icon or '',
                    is_active=bool(is_active),
                    parent=None
                ))

        if to_create:
            self.stdout.write(f"  Bulk creating {len(to_create)} missing categories...")
            ProductCategory.objects.bulk_create(to_create, batch_size=500)
            # Re-fetch target_cats to include new ones
            target_cats = {cat.name: cat for cat in ProductCategory.objects.all()}

        # 3. Update parents
        self.stdout.write("  Updating category parent relationships...")
        
        # We need a map from old_id to name to resolve parents
        old_id_to_name = {row[0]: row[1] for row in sqlite_cats}
        
        to_update = []
        for row in sqlite_cats:
            old_id, name, description, icon, is_active, parent_id = row
            if not parent_id:
                continue
                
            current_obj = target_cats.get(name)
            parent_name = old_id_to_name.get(parent_id)
            parent_obj = target_cats.get(parent_name)
            
            if current_obj and parent_obj:
                if current_obj.parent_id != parent_obj.id:
                    current_obj.parent = parent_obj
                    to_update.append(current_obj)

        if to_update:
            self.stdout.write(f"  Bulk updating {len(to_update)} parent relationships...")
            ProductCategory.objects.bulk_update(to_update, ['parent'], batch_size=500)

        self.stdout.write(f"Successfully migrated/synced categories.")


    def migrate_brands(self, cursor):
        self.stdout.write("Migrating Product Brands...")
        cursor.execute("SELECT id, name, description, is_active FROM product_brand")
        rows = cursor.fetchall()
        
        existing_brands = set(ProductBrand.objects.values_list('name', flat=True))
        
        to_create = []
        for row in rows:
            old_id, name, description, is_active = row
            if name not in existing_brands:
                to_create.append(ProductBrand(
                    name=name,
                    description=description or '',
                    is_active=bool(is_active)
                ))
        
        if to_create:
            ProductBrand.objects.bulk_create(to_create, batch_size=500)
            self.stdout.write(f"Successfully migrated {len(to_create)} brands.")
        else:
            self.stdout.write("No new brands to migrate.")

    def migrate_master_products(self, cursor):
        self.stdout.write("Migrating Master Products...")
        
        # Maps for lookup
        categories = {cat.name: cat for cat in ProductCategory.objects.all()}
        brands = {brand.name: brand for brand in ProductBrand.objects.all()}
        
        cursor.execute("SELECT id, name FROM product_category")
        old_cat_names = {row[0]: row[1] for row in cursor.fetchall()}
        
        cursor.execute("SELECT id, name FROM product_brand")
        old_brand_names = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT COUNT(*) FROM master_product")
        total_in_sqlite = cursor.fetchone()[0]
        
        # Get existing barcodes to skip
        self.stdout.write("Fetching existing barcodes from DB...")
        existing_barcodes = set(MasterProduct.objects.values_list('barcode', flat=True))
        self.stdout.write(f"Found {len(existing_barcodes)} existing products in target DB.")

        cursor.execute("SELECT barcode, name, description, image_url, attributes, brand_id, category_id, mrp FROM master_product")
        
        batch_size = 500
        migrated_count = 0
        
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
                
            to_create = []
            for row in rows:
                barcode, name, description, image_url, attributes_json, brand_id, category_id, mrp = row
                
                if barcode in existing_barcodes:
                    continue
                
                cat_obj = None
                if category_id in old_cat_names:
                    cat_obj = categories.get(old_cat_names[category_id])
                
                brand_obj = None
                if brand_id in old_brand_names:
                    brand_obj = brands.get(old_brand_names[brand_id])
                
                try:
                    attrs = json.loads(attributes_json) if attributes_json else {}
                except:
                    attrs = {}
                
                to_create.append(MasterProduct(
                    barcode=barcode,
                    name=name[:255],
                    description=description or '',
                    category=cat_obj,
                    brand=brand_obj,
                    image_url=image_url,
                    mrp=mrp,
                    attributes=attrs
                ))
                existing_barcodes.add(barcode) # Avoid dups in same batch

            if to_create:
                MasterProduct.objects.bulk_create(to_create, batch_size=batch_size)
                migrated_count += len(to_create)
                self.stdout.write(f"  Migrated {migrated_count} products...")

        self.stdout.write(f"Successfully migrated {migrated_count} master products.")


def sqlite_connect(path):
    return sqlite3.connect(path)
