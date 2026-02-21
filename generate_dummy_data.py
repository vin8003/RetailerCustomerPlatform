import os
import django
from decimal import Decimal
import random

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from django.contrib.auth import get_user_model
from retailers.models import RetailerProfile, RetailerCategory, RetailerOperatingHours, RetailerCategoryMapping
from customers.models import CustomerProfile, CustomerAddress
from products.models import Product, ProductCategory, MasterProduct

User = get_user_model()

def create_or_get_user(phone, user_type):
    user, created = User.objects.get_or_create(
        phone_number=phone,
        defaults={
            'username': phone,
            'user_type': user_type,
            'is_phone_verified': True
        }
    )
    if created:
        user.set_password('asdf@1234')
        user.save()
    return user

def generate_dummy_data():
    print("Starting data generation...")

    # 1. Retailer Categories
    print("Creating Retailer Categories...")
    grocery_cat, _ = RetailerCategory.objects.get_or_create(name='Grocery', defaults={'is_active': True})
    pharmacy_cat, _ = RetailerCategory.objects.get_or_create(name='Pharmacy', defaults={'is_active': True})

    # 2. Retailers (Pincode 321001)
    print("Creating Retailers...")
    retailers_data = [
        {
            'phone': '9999999991',
            'shop_name': 'SuperMart Bharatpur',
            'business_type': 'grocery',
            'address_line1': '101 Main Bazar',
            'city': 'Bharatpur',
            'state': 'Rajasthan',
            'pincode': '321001',
            'latitude': 27.216981,
            'longitude': 77.489517,
            'categories': [grocery_cat]
        },
        {
            'phone': '9999999992',
            'shop_name': 'City Medicos',
            'business_type': 'pharmacy',
            'address_line1': 'Opposite City Hospital',
            'city': 'Bharatpur',
            'state': 'Rajasthan',
            'pincode': '321001',
            'latitude': 27.226981,
            'longitude': 77.499517,
            'categories': [pharmacy_cat]
        },
        {
            'phone': '9999999993',
            'shop_name': 'Daily Needs Store',
            'business_type': 'grocery',
            'address_line1': 'Circular Road',
            'city': 'Bharatpur',
            'state': 'Rajasthan',
            'pincode': '321001',
            'latitude': 27.206981,
            'longitude': 77.479517,
            'categories': [grocery_cat]
        }
    ]

    retailer_profiles = []
    for r_data in retailers_data:
        phone_no = r_data.pop('phone')
        user = create_or_get_user(phone_no, 'retailer')
        
        cats = r_data.pop('categories')
        r_data['user'] = user
        r_data['is_active'] = True
        r_data.setdefault('offers_delivery', True)
        r_data.setdefault('offers_pickup', True)
        
        profile, created = RetailerProfile.objects.update_or_create(
            user=user,
            defaults=r_data
        )
        
        # Add categories
        for cat in cats:
            RetailerCategoryMapping.objects.get_or_create(retailer=profile, category=cat)
            
        print(f"Created/Updated Retailer: {profile.shop_name}")
        retailer_profiles.append(profile)

    # 3. Customers
    print("\nCreating Customers...")
    customers_data = [
        {'phone': '+918888888881', 'name': 'Rahul Sharma', 'email': 'rahul@example.com'},
        {'phone': '+918888888882', 'name': 'Priya Gupta', 'email': 'priya@example.com'},
        {'phone': '+918888888883', 'name': 'Amit Patel', 'email': 'amit@example.com'},
    ]
    
    for c_data in customers_data:
        user = create_or_get_user(c_data['phone'], 'customer')
        user.first_name = c_data['name']
        user.email = c_data.get('email', '')
        user.save()
        
        profile, created = CustomerProfile.objects.get_or_create(
            user=user
        )
        
        # Add an address in Bharatpur
        CustomerAddress.objects.get_or_create(
            customer=user,
            address_type='home',
            defaults={
                'title': f"{user.first_name}'s Home",
                'address_line1': 'House No. 123, Model Town',
                'city': 'Bharatpur',
                'state': 'Rajasthan',
                'pincode': '321001',
                'is_default': True
            }
        )
        print(f"Created/Updated Customer: {user.first_name}")

    # 4. Products for Retailers
    print("\nCreating Master Products and Products...")
    master_products_data = [
        {'name': 'Aashirvaad Atta 5kg', 'brand': 'Aashirvaad', 'mrp': 235.00, 'category': 'Staples'},
        {'name': 'Tata Salt 1kg', 'brand': 'Tata', 'mrp': 28.00, 'category': 'Staples'},
        {'name': 'Dettol Soap 125g (Pack of 4)', 'brand': 'Dettol', 'mrp': 150.00, 'category': 'Personal Care'},
        {'name': 'Maggi Noodles 280g', 'brand': 'Maggi', 'mrp': 56.00, 'category': 'Snacks'},
        {'name': 'Amul Butter 500g', 'brand': 'Amul', 'mrp': 275.00, 'category': 'Dairy'},
        {'name': 'Paracetamol 500mg (10 Tablets)', 'brand': 'Crocin', 'mrp': 25.00, 'category': 'Medicines'},
        {'name': 'Dolo 650mg (15 Tablets)', 'brand': 'Dolo', 'mrp': 30.00, 'category': 'Medicines'},
    ]

    master_products = []
    from products.models import ProductBrand, ProductCategory
    for mp_data in master_products_data:
        brand, _ = ProductBrand.objects.get_or_create(name=mp_data['brand'], defaults={'is_active': True})
        category, _ = ProductCategory.objects.get_or_create(name=mp_data['category'], defaults={'is_active': True})
        
        m_product, created = MasterProduct.objects.get_or_create(
            name=mp_data['name'],
            defaults={
                'brand': brand,
                'category': category,
                'mrp': mp_data['mrp'],
                'barcode': str(random.randint(100000000000, 999999999999))
            }
        )
        master_products.append(m_product)

    # Assign products to retailers
    for retailer in retailer_profiles:
        # Get or create global product categories
        grocery_cat, _ = ProductCategory.objects.get_or_create(name='Grocery', defaults={'is_active': True})
        med_cat, _ = ProductCategory.objects.get_or_create(name='Pharmacy', defaults={'is_active': True})

        assigned_products = []
        if retailer.business_type == 'grocery':
            assigned_products = master_products[:5]  # Grocery items
            cat = grocery_cat
        else:
            assigned_products = master_products[5:]  # Medicines
            cat = med_cat

        for idx, mp in enumerate(assigned_products):
            price = Decimal(str(mp.mrp)) * Decimal(str(round(random.uniform(0.85, 0.95), 2)))  # 5-15% discount
            
            Product.objects.get_or_create(
                retailer=retailer,
                master_product=mp,
                defaults={
                    'name': mp.name,
                    'original_price': mp.mrp,
                    'price': round(price, 2),
                    'quantity': 100,
                    'is_active': True,
                    'category': cat,
                    'barcode': mp.barcode,
                    'unit': 'piece'
                }
            )
        print(f"Added products for {retailer.shop_name}")

    print("\nDummy data generation completed successfully!")

if __name__ == '__main__':
    generate_dummy_data()
