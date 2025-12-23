from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from retailers.models import RetailerProfile
from products.models import Product, ProductCategory
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with sample products'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding data...')

        # Ensure we have a retailer
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
                'shop_name': 'Fresh Mart',
                'address_line1': '123 Market St',
                'city': 'Mumbai',
                'state': 'Maharashtra',
                'pincode': '400001',
                'shop_description': 'Best fresh produce in town',
                'offers_delivery': True,
                'minimum_order_amount': 100
            }
        )
        if created:
            self.stdout.write('Created retailer profile: Fresh Mart')

        # Create Categories
        fruits_cat, _ = ProductCategory.objects.get_or_create(name='Fruits & Vegetables')
        dairy_cat, _ = ProductCategory.objects.get_or_create(name='Dairy & Bakery')
        staples_cat, _ = ProductCategory.objects.get_or_create(name='Staples')

        # Create Products
        products_data = [
            {
                'name': 'Fresh Apples (1kg)',
                'price': 150.00,
                'category': fruits_cat,
                'unit': 'kg',
                'quantity': 100,
                'description': 'Crisp and sweet red apples.',
                # Add image url if possible or leave blank
            },
            {
                'name': 'Banana (Dozen)',
                'price': 60.00,
                'category': fruits_cat,
                'unit': 'dozen',
                'quantity': 50,
                'description': 'Ripe yellow bananas.',
            },
            {
                'name': 'Milk (1L)',
                'price': 70.00,
                'category': dairy_cat,
                'unit': 'liter',
                'quantity': 200,
                'description': 'Fresh cow milk.',
            },
            {
                'name': 'Whole Wheat Bread',
                'price': 45.00,
                'category': dairy_cat,
                'unit': 'pack',
                'quantity': 30,
                'description': 'Healthy whole wheat bread.',
            },
            {
                'name': 'Basmati Rice (5kg)',
                'price': 650.00,
                'category': staples_cat,
                'unit': 'pack',
                'quantity': 20,
                'description': 'Premium long grain basmati rice.',
            },
             {
                'name': 'Sunflower Oil (1L)',
                'price': 180.00,
                'category': staples_cat,
                'unit': 'liter',
                'quantity': 40,
                'description': 'Refined sunflower oil for cooking.',
            },
        ]

        for p_data in products_data:
            product, created = Product.objects.get_or_create(
                retailer=retailer_profile,
                name=p_data['name'],
                defaults={
                    'price': Decimal(str(p_data['price'])),
                    'category': p_data['category'],
                    'unit': p_data['unit'],
                    'quantity': p_data['quantity'],
                    'description': p_data['description'],
                    'is_active': True,
                    'is_available': True
                }
            )
            if created:
                self.stdout.write(f"Created product: {product.name}")
            else:
                self.stdout.write(f"Product already exists: {product.name}")

        self.stdout.write(self.style.SUCCESS('Successfully seeded products'))
