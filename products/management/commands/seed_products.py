from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from retailers.models import RetailerProfile
from products.models import Product, ProductCategory
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with sample products'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding enriched data...')

        # 1. Retailer Setup
        retailer_user, created = User.objects.get_or_create(
            username='retailer1',
            defaults={
                'email': 'retailer1@example.com',
                'user_type': 'retailer',
                'is_active': True
            }
        )
        if created:
            retailer_user.set_password('password123')
            retailer_user.save()
            self.stdout.write('Created retailer user: retailer1')

        retailer_profile, created = RetailerProfile.objects.get_or_create(
            user=retailer_user,
            defaults={
                'shop_name': 'Fresh Mart Superstore',
                'address_line1': 'Grand Mall, MG Road',
                'city': 'Mumbai',
                'state': 'Maharashtra',
                'pincode': '400001',
                'shop_description': 'One-stop shop for all your premium grocery and household needs.',
                'offers_delivery': True,
                'minimum_order_amount': 200
            }
        )
        if created:
            self.stdout.write('Created retailer profile: Fresh Mart Superstore')

        # 2. Category Setup
        categories_data = [
            ('Fruits & Vegetables', 'Fresh from the farm', 'shopping_basket'),
            ('Dairy & Bakery', 'Milk, eggs, and freshly baked bread', 'bakery_dining'),
            ('Beverages', 'Juices, tea, coffee and more', 'local_cafe'),
            ('Snacks & Munchies', 'Chips, biscuits and snacks', 'fastfood'),
            ('Staples', 'Rice, flour, pulses and oils', 'inventory_2'),
            ('Personal Care', 'Skin, hair and hygiene products', 'face'),
            ('Household Needs', 'Cleaning and utility items', 'cleaning_services'),
        ]

        category_map = {}
        for name, desc, icon in categories_data:
            cat, _ = ProductCategory.objects.get_or_create(
                name=name,
                defaults={'description': desc, 'icon': icon}
            )
            category_map[name] = cat

        # 3. Product Data
        products_data = [
            # Fruits & Veg
            {
                'name': 'Premium Alphonso Mangoes (1 Dozen)',
                'price': 1200.00,
                'original_price': 1500.00,
                'category': category_map['Fruits & Vegetables'],
                'unit': 'dozen',
                'quantity': 50,
                'description': 'Handpicked Rajapur Alphonso mangoes, known for their sweetness and aroma.',
                'image_url': 'https://images.unsplash.com/photo-1553279768-865429fa0078?auto=format&fit=crop&q=80&w=800',
                'is_featured': True
            },
            {
                'name': 'Organic Hass Avocado (2 units)',
                'price': 450.00,
                'category': category_map['Fruits & Vegetables'],
                'unit': 'piece',
                'quantity': 30,
                'description': 'Creamy organic Hass avocados, perfect for guacamole or toast.',
                'image_url': 'https://images.unsplash.com/photo-1523049673857-eb18f1d7b578?auto=format&fit=crop&q=80&w=800',
            },
            # Dairy & Bakery
            {
                'name': 'Artisan Sourdough Bread (400g)',
                'price': 180.00,
                'category': category_map['Dairy & Bakery'],
                'unit': 'pack',
                'quantity': 20,
                'description': 'Freshly baked sourdough with a crispy crust and soft airy center.',
                'image_url': 'https://images.unsplash.com/photo-1585478259715-876acc5be8eb?auto=format&fit=crop&q=80&w=800',
            },
            {
                'name': 'Greek Style Blueberry Yogurt (150g)',
                'price': 85.00,
                'original_price': 95.00,
                'category': category_map['Dairy & Bakery'],
                'unit': 'piece',
                'quantity': 100,
                'description': 'Thick and creamy Greek yogurt layered with real blueberries.',
                'image_url': 'https://images.unsplash.com/photo-1488477181946-6428a0291777?auto=format&fit=crop&q=80&w=800',
            },
            # Beverages
            {
                'name': 'Cold Brew Coffee Concentrate (500ml)',
                'price': 350.00,
                'category': category_map['Beverages'],
                'unit': 'bottle',
                'quantity': 40,
                'description': '100% Arabica coffee beans brewed for 18 hours for a smooth finish.',
                'image_url': 'https://images.unsplash.com/photo-1517701604599-bb29b565090c?auto=format&fit=crop&q=80&w=800',
            },
            {
                'name': 'Matcha Green Tea Powder (50g)',
                'price': 899.00,
                'original_price': 1200.00,
                'category': category_map['Beverages'],
                'unit': 'pack',
                'quantity': 15,
                'description': 'Ceremonial grade Matcha powder sourced directly from Kyoto, Japan.',
                'image_url': 'https://images.unsplash.com/photo-1582733315328-d266f8e75924?auto=format&fit=crop&q=80&w=800',
                'is_featured': True
            },
            # Snacks
            {
                'name': 'Sea Salt Dark Chocolate (100g)',
                'price': 250.00,
                'category': category_map['Snacks & Munchies'],
                'unit': 'piece',
                'quantity': 60,
                'description': '70% cocoa dark chocolate with hand-harvested sea salt.',
                'image_url': 'https://images.unsplash.com/photo-1511381939415-e44015466834?auto=format&fit=crop&q=80&w=800',
            },
            {
                'name': 'Kettle Cooked Potato Chips (150g)',
                'price': 120.00,
                'category': category_map['Snacks & Munchies'],
                'unit': 'pack',
                'quantity': 80,
                'description': 'Extra crunchy potato chips cooked in small batches.',
                'image_url': 'https://images.unsplash.com/photo-1566478989037-eec170784d0b?auto=format&fit=crop&q=80&w=800',
            },
            # Staples
            {
                'name': 'Extra Virgin Olive Oil (1L)',
                'price': 1100.00,
                'original_price': 1400.00,
                'category': category_map['Staples'],
                'unit': 'bottle',
                'quantity': 25,
                'description': 'First cold-pressed extra virgin olive oil from Spanish olives.',
                'image_url': 'https://images.unsplash.com/photo-1474979266404-7eaacabc88c5?auto=format&fit=crop&q=80&w=800',
            },
            # Personal Care
            {
                'name': 'Luxury Lavender Bath Bomb',
                'price': 199.00,
                'category': category_map['Personal Care'],
                'unit': 'piece',
                'quantity': 45,
                'description': 'Relaxing bath bomb with essential oils and dried lavender petals.',
                'image_url': 'https://images.unsplash.com/photo-1600857062241-99e5da7eb584?auto=format&fit=crop&q=80&w=800',
            }
        ]

        for p_data in products_data:
            discount_pct = 0
            if 'original_price' in p_data:
                discount_pct = ((p_data['original_price'] - p_data['price']) / p_data['original_price']) * 100

            product, created = Product.objects.update_or_create(
                retailer=retailer_profile,
                name=p_data['name'],
                defaults={
                    'price': Decimal(str(p_data['price'])),
                    'original_price': Decimal(str(p_data.get('original_price', p_data['price']))),
                    'discount_percentage': Decimal(str(discount_pct)),
                    'category': p_data['category'],
                    'unit': p_data['unit'],
                    'quantity': p_data['quantity'],
                    'description': p_data['description'],
                    'image_url': p_data.get('image_url', ''),
                    'is_featured': p_data.get('is_featured', False),
                    'is_active': True,
                    'is_available': True
                }
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f"{status} product: {product.name}")

        self.stdout.write(self.style.SUCCESS('Successfully seeded enriched products'))
