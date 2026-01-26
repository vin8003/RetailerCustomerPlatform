from django.test import TestCase
from decimal import Decimal
from django.utils import timezone
from .models import Offer, OfferTarget
from .engine import OfferEngine
from retailers.models import RetailerProfile
from products.models import Product, ProductCategory
from authentication.models import User

class MockCartItem:
    def __init__(self, product, quantity, unit_price):
        self.product = product
        self.quantity = quantity
        self.unit_price = unit_price
        
class OfferEngineTest(TestCase):
    def setUp(self):
        # Setup Retailer
        self.user = User.objects.create_user(username='testretailer', password='password')
        self.retailer = RetailerProfile.objects.create(
            user=self.user,
            shop_name="Test Shop",
            address_line1="123 Test St",
            city="Test City",
            state="Test State",
            pincode="123456"
        )
        
        # Setup Products
        self.cat1 = ProductCategory.objects.create(name="Snacks")
        
        self.prod_chips = Product.objects.create(
            retailer=self.retailer,
            name="Chips",
            price=Decimal("20.00"),
            category=self.cat1,
            quantity=100
        )
        self.prod_coke = Product.objects.create(
            retailer=self.retailer,
            name="Coke",
            price=Decimal("40.00"),
            category=self.cat1,
            quantity=100
        )
        
        self.engine = OfferEngine()

    def test_bxgy_logic(self):
        """Test Buy 2 Get 1 Free"""
        offer = Offer.objects.create(
            retailer=self.retailer,
            name="B2G1 Chips",
            offer_type='bxgy',
            buy_quantity=2,
            get_quantity=1,
            value=0,
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type='product', product=self.prod_chips)
        
        # Case 1: Buy 3 Chips -> 1 Free (Pay for 2)
        # 3 * 20 = 60. 1 Free = -20. Total = 40.
        cart = [MockCartItem(self.prod_chips, 3, Decimal("20.00"))]
        
        result = self.engine.calculate_offers(cart, self.retailer)
        
        self.assertEqual(result['total_savings'], Decimal("20.00"))
        self.assertEqual(result['discounted_total'], Decimal("40.00"))
        self.assertEqual(len(result['applied_offers']), 1)
        
        # Case 2: Buy 2 Chips -> 0 Free
        cart = [MockCartItem(self.prod_chips, 2, Decimal("20.00"))]
        result = self.engine.calculate_offers(cart, self.retailer)
        self.assertEqual(result['total_savings'], Decimal("0.00"))

    def test_percentage_discount(self):
        """Test 10% Off"""
        offer = Offer.objects.create(
            retailer=self.retailer,
            name="10% Off Coke",
            offer_type='percentage',
            value=10,
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type='product', product=self.prod_coke)
        
        # Buy 2 Cokes @ 40 = 80. 10% off = 8. Total = 72.
        cart = [MockCartItem(self.prod_coke, 2, Decimal("40.00"))]
        
        result = self.engine.calculate_offers(cart, self.retailer)
        
        self.assertEqual(result['total_savings'], Decimal("8.00"))
        self.assertEqual(result['discounted_total'], Decimal("72.00"))

    def test_cart_value_discount(self):
        """Test Flat 50 off on 100+"""
        offer = Offer.objects.create(
            retailer=self.retailer,
            name="50 off 100",
            offer_type='cart_value',
            value_type='amount',
            value=50,
            min_order_value=100,
            is_active=True
        )
        OfferTarget.objects.create(offer=offer, target_type='all_products') # Target irrelevant for cart val usually but required by engine logic
        
        # Case 1: Total 120 -> Eligible
        cart = [
            MockCartItem(self.prod_chips, 2, Decimal("20.00")), # 40
            MockCartItem(self.prod_coke, 2, Decimal("40.00")),  # 80. Total 120.
        ]
        
        result = self.engine.calculate_offers(cart, self.retailer)
        self.assertEqual(result['total_savings'], Decimal("50.00"))
        self.assertEqual(result['discounted_total'], Decimal("70.00")) # 120 - 50

        # Case 2: Total 80 -> Not Eligible
        cart = [
            MockCartItem(self.prod_coke, 2, Decimal("40.00")),  # 80
        ]
        result = self.engine.calculate_offers(cart, self.retailer)
        self.assertEqual(result['total_savings'], Decimal("0.00"))
        
    def test_mix_match_cheapest_free(self):
        """Test B2G1 Mix Match on Category"""
        offer = Offer.objects.create(
            retailer=self.retailer,
            name="B2G1 Snacks",
            offer_type='bxgy',
            buy_quantity=2,
            get_quantity=1,
            value=0,
            is_cheapest_free=True
        )
        OfferTarget.objects.create(offer=offer, target_type='category', category=self.cat1)
        
        # Buy 2 Coke (40), 1 Chips (20). Total items 3.
        # Cheapest is Chips (20). So 20 off.
        cart = [
            MockCartItem(self.prod_coke, 2, Decimal("40.00")), 
            MockCartItem(self.prod_chips, 1, Decimal("20.00"))
        ]
        # Total Value: 80 + 20 = 100.
        # Expect pay: 80. Savings: 20.
        
        result = self.engine.calculate_offers(cart, self.retailer)
        self.assertEqual(result['total_savings'], Decimal("20.00"))
        self.assertEqual(result['discounted_total'], Decimal("80.00"))
