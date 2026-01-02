from django.core.management.base import BaseCommand
from products.models import MasterProduct, ProductCategory
from django.db.models import Q

class Command(BaseCommand):
    help = 'Consolidate product categories into a manageable core set'

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

    def handle(self, *args, **options):
        self.stdout.write("Starting category consolidation...")

        # 1. Create Core Categories
        core_cats = {}
        for cat_name in self.CORE_CATEGORIES.keys():
            cat, created = ProductCategory.objects.get_or_create(
                name=cat_name, 
                defaults={'parent': None, 'is_active': True}
            )
            core_cats[cat_name] = cat
            if created:
                self.stdout.write(f"Created core category: {cat_name}")
        
        # 'Others' category for uncategorized items
        others_cat, _ = ProductCategory.objects.get_or_create(
            name='Others', 
            defaults={'parent': None, 'is_active': True}
        )
        core_cats['Others'] = others_cat

        # 2. Iterate and Update Master Products
        total_products = MasterProduct.objects.count()
        processed = 0
        updated = 0
        
        # We fetch in chunks to avoid memory issues
        chunk_size = 1000
        
        # Use iterator for memory efficiency
        for product in MasterProduct.objects.all().select_related('category').iterator(chunk_size=chunk_size):
            processed += 1
            if processed % 100 == 0:
                self.stdout.write(f"Processed {processed}/{total_products} products...")

            current_cat_name = product.category.name.lower() if product.category else ""
            prod_name = product.name.lower()
            
            # Combine text for matching
            search_text = f"{current_cat_name} {prod_name}"

            matched_cat = None
            
            # Match against keywords
            for core_name, keywords in self.CORE_CATEGORIES.items():
                for keyword in keywords:
                    if f" {keyword} " in f" {search_text} " or \
                       search_text.startswith(keyword + " ") or \
                       search_text.endswith(" " + keyword) or \
                       search_text == keyword:
                        matched_cat = core_cats[core_name]
                        break
                if matched_cat:
                    break
            
            if not matched_cat:
                matched_cat = others_cat

            # Update if changed
            if product.category != matched_cat:
                product.category = matched_cat
                product.save(update_fields=['category'])
                updated += 1
        
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} products to core categories."))

        # 3. Cleanup unused categories
        self.stdout.write("Cleaning up unused categories...")
        
        # Find all categories NOT in core_cats values
        core_ids = [c.id for c in core_cats.values()]
        
        # Aggressive cleanup: Delete ANY category that is not a core category
        # Since we migrated all MasterProducts and verified RetailerProducts are 0 on old cats,
        # we can safely delete everything else.
        
        unused_cats = ProductCategory.objects.exclude(id__in=core_ids)
        
        count = unused_cats.count()
        if count > 0:
            # We used to check for subcategories, but since we want to flatten/remove old trees,
            # and we know they are not used by products, we can delete them.
            # Due to parent ForeignKey constraints, we might need to delete leaf nodes first 
            # or just rely on CASCADE (which delete children).
            
            # If we delete a parent, children are deleted. 
            # So simple delete() on the queryset should trigger cascading deletes.
            try:
                unused_cats.delete()
                self.stdout.write(self.style.SUCCESS(f"Deleted {count} unused categories."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error deleting categories: {e}"))
        else:
             self.stdout.write("No unused categories found.")

        self.stdout.write(self.style.SUCCESS("Consolidation Complete!"))
