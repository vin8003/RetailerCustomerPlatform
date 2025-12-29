import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from products.models import MasterProduct, ProductCategory, ProductBrand
from django.db import transaction

class Command(BaseCommand):
    help = 'Import product data from OpenFoodFacts (Indian market)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Number of products to import'
        )
        parser.add_argument(
            '--page-size',
            type=int,
            default=50,
            help='Number of products per page'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        page_size = options['page_size']
        
        # Use the India specific subdomain, though param filtering is safer
        base_url = "https://in.openfoodfacts.org/cgi/search.pl"
        
        self.stdout.write(f"Starting import from OpenFoodFacts (India)...")
        
        products_imported = 0
        page = 1
        
        while products_imported < limit:
            params = {
                'search_terms': '',
                'search_simple': 1,
                'action': 'process',
                'json': 1,
                'page': page,
                'page_size': page_size,
                # Strict filtering for India
                'tagtype_0': 'countries',
                'tag_contains_0': 'contains',
                'tag_0': 'india',
                'sort_by': 'popularity',
                'fields': 'code,product_name,generic_name,brands,categories_hierarchy,image_url,image_small_url,ingredients_text,nutriments,quantity,price,serving_size,nutriscore_grade,ecoscore_grade,packaging'
            }
            
            try:
                response = requests.get(base_url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                products = data.get('products', [])
                if not products:
                    self.stdout.write("No more products found.")
                    break
                
                for item in products:
                    if products_imported >= limit:
                        break
                        
                    try:
                        self.process_product(item)
                        products_imported += 1
                        if products_imported % 10 == 0:
                            self.stdout.write(f"Processed {products_imported} products...")
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"Error processing product {item.get('code')}: {str(e)}"))
                
                page += 1
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Request failed: {str(e)}"))
                break

        self.stdout.write(self.style.SUCCESS(f"Successfully imported/updated {products_imported} products."))

    def process_product(self, item):
        code = item.get('code')
        name = item.get('product_name')
        
        if not code or not name:
            return  # Skip invalid items

        # Parse Price/MRP if available (Rare in OFF)
        mrp_value = None
        if item.get('price'):
            try:
                # Clean up string "100.00 Rs" -> 100.00
                import re
                p_str = str(item.get('price'))
                # Extract first float/int found
                matches = re.findall(r"[-+]?\d*\.\d+|\d+", p_str)
                if matches:
                    mrp_value = matches[0]
            except:
                pass
            
        # 1. Handle Brand
        brand_name = "Unknown Brand"
        if item.get('brands'):
            # Take the first brand
            brand_name = item.get('brands').split(',')[0].strip()
            
        brand, _ = ProductBrand.objects.get_or_create(
            name=brand_name[:100], # Trucate to max length
            defaults={'is_active': True}
        )
        
        # 2. Handle Categories (Hierarchy)
        category_hierarchy = item.get('categories_hierarchy', [])
        # Example: ["en:plant-based-foods-and-beverages", "en:plant-based-foods", ...]
        
        final_category = None
        parent_category = None
        
        # We'll traverse the hierarchy and create them
        # Note: determining the exact 'root' is tricky as OFF returns a flat list of tags which represents the path or mix of tags
        # But usually they are ordered generic -> specific or vice versa? 
        # Actually OFF `categories_hierarchy` is ordered.
        # "en:plant-based-foods-and-beverages", "en:plant-based-foods", "en:cereals-and-potatoes", "en:cereals", "en:wheat"
        
        # For simplicity and standardisation, let's take the LAST item as the specific category,
        # and the second to last as its parent (if it exists).
        # We don't want to create deep nesting of every single tag.
        
        if category_hierarchy:
            # Clean function
            def clean_cat(c):
                return c.split(':')[-1].replace('-', ' ').title()[:100]

            # Let's try to build a chain of max 3 levels to avoid deep recursion if the list is huge
            # Or just process the last 3 items
            
            chain = category_hierarchy[-3:] # Get last 3
            
            current_parent = None
            for cat_tag in chain:
                cat_name = clean_cat(cat_tag)
                cat_obj, _ = ProductCategory.objects.get_or_create(
                    name=cat_name,
                    defaults={'parent': current_parent, 'is_active': True}
                )
                current_parent = cat_obj
                final_category = cat_obj

        # 3. Create/Update MasterProduct
        new_attrs = {
            'generic_name': item.get('generic_name'),
            'ingredients': item.get('ingredients_text'),
            'nutriments': item.get('nutriments'),
            'quantity': item.get('quantity'),
            'serving_size': item.get('serving_size'),
            'packaging': item.get('packaging'),
            'nutriscore': item.get('nutriscore_grade'),
            'ecoscore': item.get('ecoscore_grade'),
            'image_small_url': item.get('image_small_url'),
            'off_categories': category_hierarchy
        }

        defaults = {
            'name': name[:255],
            'brand': brand,
            'category': final_category,
            'image_url': item.get('image_url'),
            'mrp': mrp_value,
            'attributes': new_attrs
        }

        product, created = MasterProduct.objects.get_or_create(
            barcode=code,
            defaults=defaults
        )

        if not created:
            # Update existing product with new data
            # strict update for core fields
            product.name = name[:255]
            product.brand = brand
            product.category = final_category
            
            # Non-destructive update for optional fields
            if item.get('image_url'):
                product.image_url = item.get('image_url')
            
            if mrp_value:
                product.mrp = mrp_value
                
            # Merge attributes
            current_attrs = product.attributes or {}
            current_attrs.update(new_attrs)
            product.attributes = current_attrs
            
            product.save()
