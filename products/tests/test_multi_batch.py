import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductBatch, ProductInventoryLog

@pytest.mark.django_db
class TestMultiBatchInventory:
    """
    Test cases for Multi-Batch inventory management
    """

    def test_sync_inventory_from_batches(self, retailer, category, brand):
        # Create a product with has_batches=True
        product = Product.objects.create(
            retailer=retailer,
            name="Batch Rice",
            category=category,
            brand=brand,
            price=Decimal("100.00"),
            has_batches=True,
            track_inventory=True
        )
        
        # Create multiple batches
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B1",
            price=Decimal("90.00"),
            original_price=Decimal("100.00"),
            quantity=50,
            is_active=True
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B2",
            price=Decimal("95.00"),
            original_price=Decimal("110.00"),
            quantity=30,
            is_active=True
        )
        
        # Sync
        product.sync_inventory_from_batches()
        
        # Verify product totals
        assert product.quantity == 80
        # Best batch (lowest price with quantity > 0) should sync to product
        assert product.price == Decimal("90.00")
        assert product.original_price == Decimal("100.00")

    def test_update_product_with_batches_api(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("update_product", args=[product.id])
        
        data = {
            "has_batches": True,
            "batches": [
                {
                    "batch_number": "NEW-BATCH-1",
                    "price": 120.00,
                    "original_price": 150.00,
                    "quantity": 40,
                    "is_active": True
                },
                {
                    "batch_number": "NEW-BATCH-2",
                    "price": 130.00,
                    "original_price": 160.00,
                    "quantity": 20,
                    "is_active": True
                }
            ]
        }
        
        response = api_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        product.refresh_from_db()
        assert product.has_batches is True
        assert product.quantity == 60
        assert product.price == Decimal("120.00")
        assert product.batches.filter(is_active=True).count() == 2

    def test_reduce_quantity_fifo_batches(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name="FIFO Rice",
            category=category,
            brand=brand,
            price=Decimal("100.00"),
            has_batches=True,
            track_inventory=True
        )
        
        # Create two batches, B1 is older (created first)
        b1 = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B1",
            price=Decimal("100.00"),
            quantity=10,
            is_active=True
        )
        b2 = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B2",
            price=Decimal("100.00"),
            quantity=10,
            is_active=True
        )
        
        product.sync_inventory_from_batches()
        assert product.quantity == 20
        
        # Reduce 15 units (should take 10 from B1 and 5 from B2)
        success = product.reduce_quantity(15)
        assert success is True
        
        b1.refresh_from_db()
        b2.refresh_from_db()
        assert b1.quantity == 0
        assert b2.quantity == 5
        
        product.refresh_from_db()
        assert product.quantity == 5

    def test_reduce_quantity_from_specific_batch(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name="Specific Batch Rice",
            category=category,
            brand=brand,
            price=Decimal("100.00"),
            has_batches=True,
            track_inventory=True
        )
        
        b1 = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B1",
            price=Decimal("100.00"),
            quantity=10,
            is_active=True
        )
        b2 = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B2",
            price=Decimal("100.00"),
            quantity=10,
            is_active=True
        )
        
        product.sync_inventory_from_batches()
        
        # Reduce 5 from B2 specifically
        success = product.reduce_quantity(5, batch=b2)
        assert success is True
        
        b1.refresh_from_db()
        b2.refresh_from_db()
        assert b1.quantity == 10
        assert b2.quantity == 5
        
        product.refresh_from_db()
        assert product.quantity == 15
