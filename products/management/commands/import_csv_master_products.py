import csv
import os
from django.core.management.base import BaseCommand
from products.models import MasterProduct, ProductCategory, ProductBrand
from django.db import transaction

class Command(BaseCommand):
    help = 'Import master products from a specific CSV file'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')
        parser.add_argument('--dry-run', action='store_true', help='Do not save changes to database')
        parser.add_argument('--limit', type=int, default=None, help='Limit the number of rows to process')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']
        dry_run = options['dry_run']
        limit = options['limit']

        if not os.path.exists(csv_file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {csv_file_path}"))
            return

        self.stdout.write(f"Starting import from {csv_file_path}...")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: No changes will be saved."))

        processed_count = 0
        created_count = 0
        updated_count = 0
        error_count = 0

        try:
            with open(csv_file_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # Check for required headers
                required_headers = ['barcode', 'brand', 'variant_name', 'primary category']
                for header in required_headers:
                    if header not in reader.fieldnames:
                        self.stdout.write(self.style.ERROR(f"Missing required header: {header}"))
                        return

                for row in reader:
                    if limit and processed_count >= limit:
                        break

                    try:
                        with transaction.atomic():
                            success = self.process_row(row, dry_run)
                            if success == 'created':
                                created_count += 1
                            elif success == 'updated':
                                updated_count += 1
                            
                        processed_count += 1
                        if processed_count % 100 == 0:
                            self.stdout.write(f"Processed {processed_count} rows...")

                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"Error processing row with barcode {row.get('barcode')}: {str(e)}"))
                        error_count += 1

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to read CSV: {str(e)}"))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Import complete: {processed_count} processed, {created_count} created, {updated_count} updated, {error_count} errors."
        ))

    def process_row(self, row, dry_run):
        barcode = row.get('barcode', '').strip()
        if not barcode:
            return None

        name = row.get('variant_name', '').strip()
        brand_name = row.get('brand', '').strip()
        primary_category_name = row.get('primary category', '').strip()
        
        # 1. Handle Brand
        brand = None
        if brand_name:
            if not dry_run:
                brand, _ = ProductBrand.objects.get_or_create(
                    name=brand_name[:100],
                    defaults={'is_active': True}
                )
        
        # 2. Handle Category
        category = None
        if primary_category_name:
            if not dry_run:
                category, _ = ProductCategory.objects.get_or_create(
                    name=primary_category_name,
                    defaults={'parent': None, 'is_active': True}
                )

        # 3. Prepare Attributes
        attributes = {
            'size': row.get('size'),
            'unit': row.get('unit'),
            'original_category': row.get('original_category'),
            'sub_category': row.get('sub category'),
            'product_group': row.get('product group'),
        }

        # 4. Create or Update MasterProduct
        defaults = {
            'name': name[:255],
            'brand': brand,
            'category': category,
            'attributes': attributes
        }

        if dry_run:
            # Check if exists
            exists = MasterProduct.objects.filter(barcode=barcode).exists()
            return 'created' if not exists else 'updated'

        product, created = MasterProduct.objects.get_or_create(
            barcode=barcode,
            defaults=defaults
        )

        if not created:
            # Update existing product
            product.name = name[:255]
            product.brand = brand
            product.category = category
            
            # Update attributes non-destructively
            current_attrs = product.attributes or {}
            current_attrs.update(attributes)
            product.attributes = current_attrs
            
            product.save()
            return 'updated'
        
        return 'created'
