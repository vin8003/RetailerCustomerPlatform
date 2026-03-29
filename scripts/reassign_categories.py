import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from products.models import Product, ProductCategory

CORE_CATEGORIES = {
    'Dairy & Bakery': ['milk', 'curd', 'yogurt', 'yoghurt', 'cheese', 'butter', 'paneer', 'cream', 'bread', 'cake', 'bakery', 'dessert', 'bun', 'rusk', 'paratha', 'roti', 'chapati', 'naan', 'kulcha', 'pav', 'muffin', 'pastry', 'croissant', 'bagel', 'dough', 'batter'],
    'Beverages': ['tea', 'coffee', 'juice', 'soda', 'drink', 'water', 'beverage', 'sharbat', 'syrup', 'coke', 'pepsi', 'sprite', 'fanta', 'limca', 'thums up', 'maaza', 'frooti', 'slice', 'real', 'tropicana', 'sting', 'red bull', 'monster', 'gatorade', 'powerade', 'glucon-d', 'tang', 'rasna', 'bournvita', 'horlicks', 'boost', 'complan', 'malt', 'cocoa', 'squash', 'crush', 'mocktail', 'cocktail', 'wine', 'beer', 'whisky', 'vodka', 'rum', 'gin', 'brandy', 'tequila', 'liquor', 'alcohol'],
    'Snacks & Munchies': ['biscuit', 'cookie', 'chip', 'crisp', 'namkeen', 'snack', 'chocolate', 'candy', 'sweet', 'popcorn', 'cracker', 'wafer', 'nacho', 'bhujia', 'sev', 'mixture', 'nut', 'dry fruit', 'seed', 'trail mix', 'bar', 'granola', 'energy bar', 'protein bar', 'gummy', 'jelly', 'marshmallow', 'lollipop', 'toffee', 'gum', 'mint', 'lozenge', 'lays', 'kurkure', 'doritos', 'cheetos'],
    'Staples & Spices': ['rice', 'flour', 'atta', 'dal', 'pulse', 'oil', 'ghee', 'salt', 'sugar', 'spice', 'masala', 'condiment', 'sauce', 'paste', 'pickle', 'papad', 'grain', 'cereal', 'wheat', 'maida', 'suji', 'rawa', 'besan', 'corn', 'millet', 'oat', 'quinoa', 'barley', 'jaggery', 'honey', 'molasses', 'vinegar', 'ketchup', 'mayonnaise', 'mustard', 'chilli', 'chili', 'pepper', 'turmeric', 'coriander', 'cumin', 'fenugreek', 'cardamom', 'clove', 'cinnamon', 'nutmeg', 'saffron', 'vanilla', 'yeast', 'baking', 'powder', 'soda', 'essence', 'color', 'flavour', 'flavor'],
    'Instant Food & Noodles': ['noodle', 'pasta', 'soup', 'instant', 'ready to eat', 'frozen', 'maggi', 'yippee', 'top ramen', 'ching', 'knorr', 'cup', 'meal', 'mix', 'packet', 'sachet', 'bowl', 'macaroni', 'spaghetti', 'vermicelli', 'fusilli', 'penne', 'lasagna', 'ravioli', 'pizza', 'burger', 'fries', 'nugget', 'sausage', 'bacon', 'ham', 'salami'],
    'Personal Care': ['soap', 'shampoo', 'wash', 'tooth', 'paste', 'brush', 'hair', 'skin', 'face', 'cream', 'lotion', 'gel', 'powder', 'deo', 'perfume', 'scent', 'fragrance', 'makeup', 'lipstick', 'liner', 'mascara', 'shadow', 'foundation', 'concealer', 'blush', 'bronzer', 'highlighter', 'primer', 'remover', 'cleanser', 'toner', 'moisturizer', 'serum', 'mask', 'scrub', 'balm', 'oil', 'shave', 'razor', 'blade', 'foam', 'aftershave', 'beared', 'trimmer', 'grooming', 'sanitary', 'pad', 'napkin', 'tampon', 'hygiene', 'condom', 'contraceptive', 'lubricant', 'pregnancy', 'test'],
    'Household Needs': ['detergent', 'cleaner', 'dish', 'floor', 'toilet', 'repel', 'freshener', 'mosquito', 'insect', 'mat', 'coil', 'liquid', 'spray', 'refill', 'bulb', 'light', 'battery', 'cell', 'torch', 'candle', 'match', 'box', 'lighter', 'incense', 'stick', 'agarbatti', 'dhoop', 'camphor', 'puja', 'worship', 'god', 'idol', 'tissue', 'paper', 'towel', 'foil', 'wrap', 'bag', 'bin', 'garbage', 'dust', 'broom', 'mop', 'scrubber', 'sponge', 'glove', 'sanitizer', 'disinfectant', 'bleach', 'acid', 'harpic', 'lizol', 'colin', 'vim', 'prill', 'surf', 'ariel', 'tide', 'wheel', 'rin', 'comfort', 'lenor', 'vanish'],
    'Baby Care': ['diaper', 'baby', 'wipe', 'food', 'formula', 'porridge', 'puree', 'teether', 'soother', 'pacifier', 'bottle', 'nipple', 'sipper', 'bib', 'apron', 'clothing', 'shoe', 'sock', 'bootie', 'mitten', 'cap', 'hat', 'blanket', 'swaddle', 'pram', 'carrier', 'seat', 'bed', 'cot', 'mattress'],
    'Pet Care': ['dog', 'cat', 'pet', 'treat', 'chew', 'bone', 'collar', 'leash', 'harness', 'cage', 'crate', 'litter', 'sand', 'tray', 'scoop', 'medicine', 'vitamin', 'supplement'],
    'Fruits & Vegetables': ['fruit', 'vegetable', 'fresh', 'apple', 'banana', 'orange', 'grape', 'mango', 'pineapple', 'watermelon', 'melon', 'papaya', 'guava', 'pomegranate', 'kiwi', 'pear', 'peach', 'plum', 'cherry', 'berry', 'strawberry', 'blueberry', 'raspberry', 'blackberry', 'cranberry', 'date', 'fig', 'apricot', 'raisin', 'prune', 'potato', 'onion', 'tomato', 'garlic', 'ginger', 'brinjal', 'eggplant', 'okra', 'ladyfinger', 'pumpkin', 'gourd', 'squash', 'mushroom', 'lemon', 'lime', 'citrus', 'herb', 'parsley', 'basil', 'oregano', 'thyme', 'rosemary', 'curry', 'leaf', 'capsicum', 'cucumber', 'carrot', 'radish', 'beetroot', 'turnip', 'sweet', 'corn', 'pea', 'bean', 'spinach', 'lettuce', 'cabbage', 'cauliflower', 'broccoli'],
    'Breakfast & Cereals': ['muesli', 'flake', 'cornflakes', 'chocos', 'loops', 'crunch', 'bran', 'preserve', 'conserve', 'maple', 'peanut butter', 'nutella', 'marmalade'],
    'Stationery & Office': ['pen', 'pencil', 'notebook', 'paper', 'eraser', 'sharpener', 'ruler', 'scale', 'marker', 'highlighter', 'folder', 'file', 'stapler', 'staple', 'clip', 'pin', 'glue', 'tape', 'scissor', 'cutter', 'calculator', 'envelope', 'stamp', 'ink', 'paint', 'color', 'brush', 'crayon', 'chalk', 'board', 'chart', 'map', 'globe', 'diary', 'calendar', 'planner', 'organizer', 'desk', 'chair', 'table', 'lamp']
}

def analyze_and_reassign():
    print("Pre-creating Root Categories based on Platform Standard...")
    cat_objs = {}
    others_cat, _ = ProductCategory.objects.get_or_create(name='Others', retailer=None, defaults={'is_active': True})
    
    for core_name in CORE_CATEGORIES.keys():
        cat, _ = ProductCategory.objects.get_or_create(name=core_name, retailer=None, defaults={'is_active': True})
        cat_objs[core_name] = cat
        
    print("Starting mass-reassignment for Uncategorized Products...")
    
    uncat_products = Product.objects.filter(category__isnull=True)
    total = uncat_products.count()
    print(f"Total Uncategorized Products to scan: {total}")
    
    updates = 0
    batch = []
    
    for product in uncat_products.iterator(chunk_size=1000):
        search_text = product.name.lower()
        if product.brand:
            search_text += " " + product.brand.name.lower()
            
        matched_cat = others_cat
        
        for core_name, keywords in CORE_CATEGORIES.items():
            found = False
            for keyword in keywords:
                # Exact or boundary matching
                if f" {keyword} " in f" {search_text} " or search_text.startswith(keyword + " ") or search_text.endswith(" " + keyword) or search_text == keyword:
                     matched_cat = cat_objs[core_name]
                     found = True
                     break
            if found:
                break
                
        product.category = matched_cat
        batch.append(product)
        updates += 1
        
        if len(batch) >= 1000:
            Product.objects.bulk_update(batch, ['category'])
            print(f"Processed {updates}/{total}...")
            batch = []
            
    if batch:
        Product.objects.bulk_update(batch, ['category'])
        print(f"Processed {updates}/{total}...")
        
    print(f"Successfully reassigned {updates} products!")

if __name__ == '__main__':
    analyze_and_reassign()
