from django.core.management.base import BaseCommand
from products.models import MasterProduct, ProductBrand
from django.db.models import Q

class Command(BaseCommand):
    help = 'Consolidate product brands by normalizing names and merging duplicates'

    # Canonical mapping: Lowercase Key -> Canonical Title Case Name
    BRAND_MAPPINGS = {
        'nestlé': 'Nestle',
        'nestle': 'Nestle',
        'haldiram': "Haldiram's",
        "haldiram's": "Haldiram's",
        "haldirams": "Haldiram's",
        'hul': 'Hindustan Unilever',
        'hindustan unilever': 'Hindustan Unilever',
        'itc': 'ITC',
        'amul': 'Amul',
        'britania': 'Britannia',
        'britannia': 'Britannia',
        'parle': 'Parle',
        'parle agro': 'Parle', # Maybe keep separate? Usually Parle covers both for simplicity in retail
        'cadbury': 'Cadbury',
        'mondelez': 'Cadbury', # Often labelled interchangeably in India
        'pepsi': 'PepsiCo',
        'pepsico': 'PepsiCo',
        'coca cola': 'Coca-Cola',
        'coca-cola': 'Coca-Cola',
        'coke': 'Coca-Cola',
        'unknown brand': None, # We will try to extract from name if possible, else keep null or "General"
    }

    def handle(self, *args, **options):
        self.stdout.write("Starting brand consolidation...")
        
        # Helper to get/create canonical brand
        canonical_brand_cache = {}

        def get_canonical_brand(name):
            if not name:
                return None
            
            clean_name = name.strip()
            lower_name = clean_name.lower()
            
            # Check manual mapping first
            if lower_name in self.BRAND_MAPPINGS:
                mapped_name = self.BRAND_MAPPINGS[lower_name]
                if mapped_name is None:
                    return None # Explicit removal (Unknown Brand)
                clean_name = mapped_name
            else:
                # Default normalization: Title Case
                clean_name = clean_name.title()
            
            if clean_name in canonical_brand_cache:
                return canonical_brand_cache[clean_name]
            
            brand, _ = ProductBrand.objects.get_or_create(
                name=clean_name,
                defaults={'is_active': True}
            )
            canonical_brand_cache[clean_name] = brand
            return brand

        # Iterate over MasterProducts
        total_products = MasterProduct.objects.count()
        processed = 0
        updated = 0
        
        chunk_size = 1000
        for product in MasterProduct.objects.all().select_related('brand').iterator(chunk_size=chunk_size):
            processed += 1
            if processed % 1000 == 0:
                self.stdout.write(f"Processed {processed}/{total_products} products...")

            current_brand_name = product.brand.name if product.brand else None
            
            # Use existing brand name if present, else try to find something (maybe from name?)
            # For now, we rely on what's in the 'brand' field or the product name if needed?
            # The import script usually sets the brand.
            
            if not current_brand_name:
                continue

            new_brand = get_canonical_brand(current_brand_name)
            
            if product.brand != new_brand:
                product.brand = new_brand
                product.save(update_fields=['brand'])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} products to canonical brands."))
        
        # Cleanup unused brands
        self.stdout.write("Cleaning up unused brands...")
        
        # We need to be careful with Retailer Products.
        # But we can assume we want to clean up unused ones aggressively same as categories?
        # Let's check if they are used by ANY product (Master or Retailer)
        
        # It's better to keep brands if they are used by Retailer Products.
        # So we delete where BOTH master and retailer counts are 0.
        
        unused_brands = ProductBrand.objects.filter(
            master_products__isnull=True,
            products__isnull=True
        )
        
        count = unused_brands.count()
        if count > 0:
             # Delete in chunks if too many?
            unused_brands.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {count} unused brands."))
        else:
            self.stdout.write("No unused brands found.")

        self.stdout.write(self.style.SUCCESS("Brand Consolidation Complete!"))
