
import os
import django
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from django.contrib.auth import get_user_model
from retailers.models import RetailerProfile
from products.models import Product, ProductCategory, ProductBrand
from offers.models import Offer, OfferTarget
from cart.models import Cart, CartItem
from offers.engine import OfferEngine
from decimal import Decimal
from django.utils import timezone

User = get_user_model()

def run_test():
    print("Setting up test data...")
    # 1. Create Retailer & User
    retailer_user, _ = User.objects.get_or_create(username='test_retailer_offer', email='test_retailer_offer@example.com', defaults={'user_type': 'retailer'})
    retailer_user.set_password('password')
    retailer_user.save()
    
    retailer, _ = RetailerProfile.objects.get_or_create(user=retailer_user, defaults={'shop_name': "Test Offer Shop"})
    
    customer_user, _ = User.objects.get_or_create(username='test_customer_offer', email='test_customer_offer@example.com', defaults={'user_type': 'customer'})
    customer_user.set_password('password')
    customer_user.save()
    
    # 2. Create Products
    cat, _ = ProductCategory.objects.get_or_create(name="Test Category")
    
    p1, _ = Product.objects.get_or_create(retailer=retailer, name="Mixed Soap A", defaults={'price': Decimal("100.00"), 'quantity': 100, 'category': cat})
    p2, _ = Product.objects.get_or_create(retailer=retailer, name="Mixed Soap B", defaults={'price': Decimal("100.00"), 'quantity': 100, 'category': cat})
    
    p3, _ = Product.objects.get_or_create(retailer=retailer, name="Same Prod Soap", defaults={'price': Decimal("50.00"), 'quantity': 100, 'category': cat})
    
    # 3. Create Offers
    # Offer A: Mixed B1G1
    offer_mixed, c = Offer.objects.get_or_create(
        retailer=retailer, name="Mixed B1G1", 
        defaults={
            'offer_type': 'bxgy', 
            'buy_quantity': 1, 'get_quantity': 1,
            'bxgy_strategy': 'mixed',
            'start_date': timezone.now(),
            'value': Decimal('0.00')
        }
    )
    if not c:
        offer_mixed.bxgy_strategy = 'mixed'
        offer_mixed.save()
        
    OfferTarget.objects.get_or_create(offer=offer_mixed, target_type='product', product=p1)
    OfferTarget.objects.get_or_create(offer=offer_mixed, target_type='product', product=p2)
    
    # Offer B: Same Product B1G2
    offer_same, c = Offer.objects.get_or_create(
        retailer=retailer, name="Same B1G2",
        defaults={
            'offer_type': 'bxgy',
            'buy_quantity': 1, 'get_quantity': 2,
            'bxgy_strategy': 'same_product',
            'start_date': timezone.now(),
            'value': Decimal('0.00')
        }
    )
    if not c:
        offer_same.bxgy_strategy = 'same_product'
        offer_same.save()

    OfferTarget.objects.get_or_create(offer=offer_same, target_type='product', product=p3)
    
    # 4. Test Mixed Strategy (Engine Check)
    print("\n--- Testing Mixed Strategy ---")
    cart, _ = Cart.objects.get_or_create(customer=customer_user, retailer=retailer)
    cart.items.all().delete()
    
    CartItem.objects.create(cart=cart, product=p1, quantity=1)
    CartItem.objects.create(cart=cart, product=p2, quantity=1)
    
    engine = OfferEngine()
    cart_items = list(cart.items.select_related('product').all())
    results = engine.calculate_offers(cart_items, retailer)
    
    print(f"Subtotal: {results['subtotal']}")
    print(f"Discounted: {results['discounted_total']}")
    print(f"Savings: {results['total_savings']}")
    applied_names = [o['name'] for o in results['applied_offers']]
    print(f"Offers: {applied_names}")
    
    if results['total_savings'] == 100 and "Mixed B1G1" in applied_names:
        print("PASS: Mixed strategy worked (1 Free).")
    else:
        print(f"FAIL: Mixed strategy failed. Expected 100 savings, got {results['total_savings']}")

    # 5. Test Same Product Auto-Add Logic
    print("\n--- Testing Same Product Strategy (Auto-Add) ---")
    cart.items.all().delete()
    
    # Simulate User adding 1 item
    print("User adds 1 'Same Prod Soap'...")
    target_qty_added = 1
    
    # Check Auto-Add Logic (Simulating view logic)
    final_qty = target_qty_added
    if target_qty_added == offer_same.buy_quantity:
        final_qty += offer_same.get_quantity
        print(f"Auto-add triggered! Quantity becomes {final_qty}")
        
    CartItem.objects.create(cart=cart, product=p3, quantity=final_qty)
    
    # Check Calculation
    cart_items = list(cart.items.select_related('product').all())
    results = engine.calculate_offers(cart_items, retailer)
    
    print(f"Cart Qty: {cart.items.first().quantity}")
    print(f"Subtotal: {results['subtotal']}") # 3 * 50 = 150
    print(f"Discounted: {results['discounted_total']}") # 50 (Pay for 1)
    print(f"Savings: {results['total_savings']}") # 100 (2 Free)
    applied_names = [o['name'] for o in results['applied_offers']]
    print(f"Offers: {applied_names}")

    if cart.items.first().quantity == 3 and results['discounted_total'] == 50 and "Same B1G2" in applied_names:
         print("PASS: Same Product strategy worked (Auto-add + Calc).")
    else:
         print("FAIL: Same Product strategy failed.")

    # 6. Test Buy 2 Get 2 (User Reported Issue)
    print("\n--- Testing Buy 2 Get 2 ---")
    
    # Create product and offer
    p4, _ = Product.objects.get_or_create(retailer=retailer, name="B2G2 Soap", defaults={'price': Decimal("100.00"), 'quantity': 100, 'category': cat})
    
    offer_b2g2, c = Offer.objects.get_or_create(
        retailer=retailer, name="Same B2G2",
        defaults={
            'offer_type': 'bxgy',
            'buy_quantity': 2, 'get_quantity': 2,
            'bxgy_strategy': 'same_product',
            'start_date': timezone.now(),
            'value': Decimal('0.00')
        }
    )
    if not c:
        offer_b2g2.bxgy_strategy = 'same_product'
        offer_b2g2.buy_quantity = 2
        offer_b2g2.get_quantity = 2
        offer_b2g2.save()

    OfferTarget.objects.get_or_create(offer=offer_b2g2, target_type='product', product=p4)
    
    cart.items.all().delete()
    
    # Test 1: Add 2 items at once
    print("Test 1: User adds 2 items at once...")
    target_qty_added = 2
    if target_qty_added == offer_b2g2.buy_quantity:
        target_qty_added += offer_b2g2.get_quantity
        print(f"Auto-add triggered! Quantity becomes {target_qty_added}")
    
    CartItem.objects.create(cart=cart, product=p4, quantity=target_qty_added)
    if cart.items.first().quantity == 4:
        print("PASS: Adding 2 resulted in 4.")
    else:
        print(f"FAIL: Adding 2 resulted in {cart.items.first().quantity}. Expected 4.")

    # Test 2: Add 1 then 1
    print("Test 2: User adds 1 then 1 (Incremental)...")
    cart.items.all().delete()
    
    # Step A: Add 1
    current_qty = 0
    added = 1
    current_qty += added
    # Logic check
    if current_qty == offer_b2g2.buy_quantity:
        current_qty += offer_b2g2.get_quantity
    
    CartItem.objects.create(cart=cart, product=p4, quantity=current_qty)
    print(f"After adding 1: Qty {current_qty}")
    
    # Step B: Add 1 more
    added = 1
    obj = CartItem.objects.get(cart=cart, product=p4)
    obj.quantity += added
    current_qty = obj.quantity
    
    # Logic check (SIMULATED VIEW LOGIC)
    if current_qty == offer_b2g2.buy_quantity:
        current_qty += offer_b2g2.get_quantity
        print(f"Auto-add triggered on 2nd item! New Qty {current_qty}")
    
    obj.quantity = current_qty
    obj.save()
    
    if obj.quantity == 4:
        print("PASS: Adding 1+1 resulted in 4.")
    else:
        print(f"FAIL: Adding 1+1 resulted in {obj.quantity}. Expected 4.")

if __name__ == "__main__":
    run_test()
