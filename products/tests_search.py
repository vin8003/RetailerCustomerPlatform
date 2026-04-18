import time
from django.test import TestCase
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient
from retailers.models import RetailerProfile
from products.models import Product, ProductCategory, ProductBrand, MasterProduct, SearchTelemetry
from django.contrib.auth import get_user_model
User = get_user_model()
from decimal import Decimal
from django.contrib.postgres.operations import TrigramExtension

class ProductSearchTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure pg_trgm is created in the test DB
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            
    def setUp(self):
        # Create standard user and retailer
        self.user = User.objects.create_user(
            username='+919999999999', 
            password='testpassword',
            user_type='retailer',
            phone_number='+919999999999'
        )
        self.retailer = RetailerProfile.objects.create(
            user=self.user,
            shop_name="Test Shop",
            business_type="grocery"
        )
        
        # Create categories and brands
        self.cat_dairy = ProductCategory.objects.create(name="Dairy", is_active=True)
        self.brand_amul = ProductBrand.objects.create(name="Amul", is_active=True)
        
        # Product 1: High stock, no discount, exact match "Milk"
        self.p1 = Product.objects.create(
            retailer=self.retailer,
            name="Amul Full Cream Milk 1L",
            price=Decimal("66.00"),
            original_price=Decimal("66.00"),
            quantity=50,
            category=self.cat_dairy,
            brand=self.brand_amul,
            is_active=True,
            barcode="8901262010013"
        )
        # Note: No custom save() behavior called to set discount yet
        self.p1.save()
        
        # Product 2: Out of stock exact match
        self.p2 = Product.objects.create(
            retailer=self.retailer,
            name="Mother Dairy Toned Milk 1L",
            price=Decimal("54.00"),
            original_price=Decimal("54.00"),
            quantity=0, # Out of stock
            category=self.cat_dairy,
            is_active=True
        )
        
        # Product 3: Discounted item
        self.p3 = Product.objects.create(
            retailer=self.retailer,
            name="Amul Butter 100g",
            price=Decimal("45.00"),
            original_price=Decimal("50.00"), # Triggers discount calculation in save()
            quantity=10,
            category=self.cat_dairy,
            brand=self.brand_amul,
            is_active=True
        )

        # Product 4: fallback-only term in description (substring, not full-text token match)
        self.p4 = Product.objects.create(
            retailer=self.retailer,
            name="Special Dairy Item",
            description="ultrararetoken",
            price=Decimal("30.00"),
            original_price=Decimal("30.00"),
            quantity=5,
            category=self.cat_dairy,
            is_active=True
        )
        self.client = APIClient()

    def test_search_typo_tolerance_trigram(self):
        """Test that a typo (e.g. 'amull milk') still returns the correct product via pg_trgm."""
        from products.views import smart_product_search
        queryset = Product.objects.filter(retailer=self.retailer, is_active=True)
        
        # "amull" instead of "amul"
        results = smart_product_search(queryset, "amull milk")
        
        self.assertTrue(results.exists(), "Trigram similarity failed to find a match for typo.")
        names = [r.name for r in results]
        
        # It should rank based on fuzzy match
        self.assertIn("Amul Full Cream Milk 1L", names)

    def test_search_business_logic_ranking(self):
        """Test that ranking prefers in-stock over out-of-stock items"""
        from products.views import smart_product_search
        queryset = Product.objects.filter(retailer=self.retailer, is_active=True)
        
        results = list(smart_product_search(queryset, "Milk"))
        
        # P1 (in stock) should be ranked higher than P2 (out of stock)
        p1_index = next(i for i, r in enumerate(results) if r.id == self.p1.id)
        p2_index = next(i for i, r in enumerate(results) if r.id == self.p2.id)
        
        self.assertLess(p1_index, p2_index, "In-stock item was not ranked higher than out-of-stock item.")

    def test_telemetry_logging(self):
        """Test search telemetry logging asynchronously (simulated)"""
        from products.views import log_search_telemetry
        
        initial_count = SearchTelemetry.objects.count()
        log_search_telemetry("testing telemetry", 5, retailer=self.retailer, user=self.user)
        
        # Verify it was logged
        self.assertEqual(SearchTelemetry.objects.count(), initial_count + 1)
        log = SearchTelemetry.objects.last()
        self.assertEqual(log.query, "testing telemetry")
        self.assertEqual(log.result_count, 5)

    def test_smart_product_search_fallback_still_returns_icontains_matches(self):
        """Regression: fallback branch remains compatible when smart scoring yields no rows."""
        from products.views import smart_product_search
        queryset = Product.objects.filter(retailer=self.retailer, is_active=True)

        results = list(smart_product_search(queryset, "raretok"))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, self.p4.id)

    def test_search_products_response_schema_and_ordering_regression(self):
        """Regression: authenticated search keeps response schema/facets and ranking order."""
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse('search_products'), {'search': 'milk', 'limit': 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data.keys()), {'results', 'facets'})
        self.assertEqual(set(response.data['facets'].keys()), {'categories', 'brands'})

        result_ids = [item['id'] for item in response.data['results']]
        self.assertEqual(result_ids, [self.p1.id, self.p2.id])

    def test_search_products_public_response_schema_and_ordering_regression(self):
        """Regression: public search keeps response schema/facets and ranking order."""
        response = self.client.get(
            reverse('search_products_public', args=[self.retailer.id]),
            {'search': 'milk', 'limit': 2}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data.keys()), {'results', 'facets'})
        self.assertEqual(set(response.data['facets'].keys()), {'categories', 'brands'})

        result_ids = [item['id'] for item in response.data['results']]
        self.assertEqual(result_ids, [self.p1.id, self.p2.id])
