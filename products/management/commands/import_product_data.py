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
        if item.get('brands'):
            # Take the first brand
            brand_name = item.get('brands').split(',')[0].strip()
        
        # Normalize Brand
        # Copy of logic from consolidate_brands.py
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
            'parle agro': 'Parle',
            'cadbury': 'Cadbury',
            'mondelez': 'Cadbury',
            'pepsi': 'PepsiCo',
            'pepsico': 'PepsiCo',
            'coca cola': 'Coca-Cola',
            'coca-cola': 'Coca-Cola',
            'coke': 'Coca-Cola',
            'unknown brand': None,
        }
        
        normalized_brand = "Unknown Brand"
        if brand_name:
            lower = brand_name.lower()
            if lower in BRAND_MAPPINGS:
                normalized_brand = BRAND_MAPPINGS[lower]
            else:
                normalized_brand = brand_name.title()
                
        if not normalized_brand:
            normalized_brand = "Unknown Brand"
            
        brand, _ = ProductBrand.objects.get_or_create(
            name=normalized_brand[:100], 
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

            # Simplified: Map OFF tags to Core Categories directly matching logic in consolidate_categories.py
            CORE_CATEGORIES = {
                'Dairy & Bakery': ['milk', 'curd', 'yogurt', 'yoghurt', 'cheese', 'butter', 'paneer', 'cream', 'bread', 'cake', 'bakery', 'dessert', 'bun', 'rusk', 'paratha', 'roti', 'chapati', 'naan', 'kulcha', 'pav', 'muffin', 'pastry', 'croissant', 'bagel', 'dough', 'batter'],
                'Beverages': ['tea', 'coffee', 'juice', 'soda', 'drink', 'water', 'beverage', 'sharbat', 'syrup', 'coke', 'pepsi', 'sprite', 'fanta', 'limca', 'thums up', 'maaza', 'frooti', 'slice', 'real', 'tropicana', 'sting', 'red bull', 'monster', 'gatorade', 'powerade', 'glucon-d', 'tang', 'rasna', 'bournvita', 'horlicks', 'boost', 'complan', 'malt', 'cocoa', 'squash', 'crush', 'mocktail', 'cocktail', 'wine', 'beer', 'whisky', 'vodka', 'rum', 'gin', 'brandy', 'tequila', 'liquor', 'alcohol'],
                'Snacks & Munchies': ['biscuit', 'cookie', 'chip', 'crisp', 'namkeen', 'snack', 'chocolate', 'candy', 'sweet', 'popcorn', 'cracker', 'wafer', 'nacho', 'bhujia', 'sev', 'mixture', 'nut', 'dry fruit', 'seed', 'trail mix', 'bar', 'granola', 'energy bar', 'protein bar', 'gummy', 'jelly', 'marshmallow', 'lollipop', 'toffee', 'gum', 'mint', 'lozenge'],
                'Staples & Spices': ['rice', 'flour', 'atta', 'dal', 'pulse', 'oil', 'ghee', 'salt', 'sugar', 'spice', 'masala', 'condiment', 'sauce', 'paste', 'pickle', 'papad', 'grain', 'cereal', 'wheat', 'maida', 'suji', 'rawa', 'besan', 'corn', 'millet', 'oat', 'quinoa', 'barley', 'sugar', 'jaggery', 'honey', 'molasses', 'syrup', 'vinegar', 'ketchup', 'mayonnaise', 'mustard', 'chilli', 'chili', 'pepper', 'turmeric', 'coriander', 'cumin', 'fenugreek', 'cardamom', 'clove', 'cinnamon', 'nutmeg', 'saffron', 'vanilla', 'yeast', 'baking', 'powder', 'soda', 'essence', 'color', 'flavour', 'flavor'],
                'Instant Food & Noodles': ['noodle', 'pasta', 'soup', 'instant', 'ready to eat', 'frozen', 'maggi', 'yippee', 'top ramen', 'ching', 'knorr', 'soup', 'cup', 'meal', 'mix', 'packet', 'sachet', 'bowl', 'macaroni', 'spaghetti', 'vermicelli', 'fusilli', 'penne', 'lasagna', 'ravioli', 'pizza', 'burger', 'fries', 'nugget', 'sausage', 'bacon', 'ham', 'salami'],
                'Personal Care': ['soap', 'shampoo', 'wash', 'tooth', 'paste', 'brush', 'hair', 'skin', 'face', 'cream', 'lotion', 'gel', 'powder', 'deo', 'perfume', 'scent', 'fragrance', 'makeup', 'lipstick', 'liner', 'mascara', 'shadow', 'foundation', 'concealer', 'blush', 'bronzer', 'highlighter', 'primer', 'remover', 'cleanser', 'toner', 'moisturizer', 'serum', 'mask', 'scrub', 'balm', 'oil', 'shave', 'razor', 'blade', 'foam', 'aftershave', 'beared', 'trimmer', 'grooming', 'sanitary', 'pad', 'napkin', 'tampon', 'cup', 'hygiene', 'condom', 'contraceptive', 'lubricant', 'pregnancy', 'test'],
                'Household Needs': ['detergent', 'cleaner', 'wash', 'dish', 'floor', 'toilet', 'repel', 'freshener', 'mosquito', 'insect', 'mat', 'coil', 'liquid', 'spray', 'refill', 'bulb', 'light', 'battery', 'cell', 'torch', 'candle', 'match', 'box', 'lighter', 'incense', 'stick', 'agarbatti', 'dhoop', 'camphor', 'puja', 'worship', 'god', 'idol', 'tissue', 'paper', 'napkin', 'towel', 'foil', 'wrap', 'bag', 'bin', 'garbage', 'dust', 'broom', 'mop', 'brush', 'scrubber', 'sponge', 'glove', 'mask', 'sanitizer', 'disinfectant', 'bleach', 'acid', 'harpic', 'lizol', 'colin', 'vim', 'prill', 'surf', 'ariel', 'tide', 'wheel', 'rin', 'comfort', 'lenor', 'vanish'],
                'Baby Care': ['diaper', 'baby', 'wipe', 'food', 'milk', 'formula', 'cereal', 'porridge', 'puree', 'juice', 'snack', 'biscuit', 'cookie', 'teether', 'soother', 'pacifier', 'bottle', 'nipple', 'sipper', 'cup', 'bowl', 'plate', 'spoon', 'fork', 'bib', 'apron', 'clothing', 'shoe', 'sock', 'bootie', 'mitten', 'cap', 'hat', 'blanket', 'swaddle', 'wrap', 'towel', 'cloth', 'napkin', 'tissue', 'wet', 'dry', 'cream', 'lotion', 'oil', 'powder', 'shampoo', 'wash', 'soap', 'bath', 'tub', 'toy', 'rattle', 'walker', 'stroller', 'pram', 'carrier', 'seat', 'bed', 'cot', 'mattress'],
                'Pet Care': ['dog', 'cat', 'pet', 'food', 'treat', 'snack', 'biscuit', 'chew', 'bone', 'stick', 'toy', 'ball', 'rope', 'collar', 'leash', 'harness', 'bed', 'mat', 'cage', 'crate', 'carrier', 'bowl', 'shampoo', 'soap', 'brush', 'comb', 'litter', 'sand', 'tray', 'scoop', 'medicine', 'vitamin', 'supplement'],
                'Fruits & Vegetables': ['fruit', 'vegetable', 'fresh', 'apple', 'banana', 'orange', 'grape', 'mango', 'pineapple', 'watermelon', 'melon', 'papaya', 'guava', 'pomegranate', 'kiwi', 'pear', 'peach', 'plum', 'cherry', 'berry', 'strawberry', 'blueberry', 'raspberry', 'blackberry', 'cranberry', 'date', 'fig', 'apricot', 'raisin', 'prune', 'potato', 'onion', 'tomato', 'garlic', 'ginger', 'chilli', 'pepper', 'capsicum', 'cucumber', 'carrot', 'radish', 'beetroot', 'turnip', 'sweet', 'corn', 'pea', 'bean', 'spinach', 'lettuce', 'cabbage', 'cauliflower', 'broccoli', 'brinjal', 'eggplant', 'okra', 'ladyfinger', 'pumpkin', 'gourd', 'squash', 'mushroom', 'lemon', 'lime', 'citrus', 'herb', 'coriander', 'mint', 'parsley', 'basil', 'oregano', 'thyme', 'rosemary', 'curry', 'leaf'],
                'Breakfast & Cereals': ['oat', 'muesli', 'flake', 'cornflakes', 'chocos', 'loops', 'crunch', 'wheat', 'bran', 'honey', 'jam', 'spread', 'butter', 'peanut', 'almond', 'cashew', 'hazelnut', 'nutella', 'marmalade', 'preserve', 'conserve', 'syrup', 'maple', 'chocolate', 'fruit', 'berry'],
            }
            
            # Helper to create core cats if not exist (should be created by migration script but just in case)
            def get_core_cat(name):
                cat, _ = ProductCategory.objects.get_or_create(
                    name=name,
                    defaults={'parent': None, 'is_active': True}
                )
                return cat
            
            # Fallback
            others_cat = get_core_cat('Others')
            
            search_text = " ".join([clean_cat(c) for c in category_hierarchy]).lower() + " " + name.lower()
            
            matched_cat_name = None
            for core_name, keywords in CORE_CATEGORIES.items():
                for keyword in keywords:
                    if f" {keyword} " in f" {search_text} " or \
                       search_text.startswith(keyword + " ") or \
                       search_text.endswith(" " + keyword) or \
                       search_text == keyword:
                        matched_cat_name = core_name
                        break
                if matched_cat_name:
                    break
            
            if matched_cat_name:
                final_category = get_core_cat(matched_cat_name)
            else:
                final_category = others_cat

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
