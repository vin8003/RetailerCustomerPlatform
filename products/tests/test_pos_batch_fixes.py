import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductBatch, ProductInventoryLog
from orders.models import Order
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestPOSPriceValidation:
    """
    Tests for POS checkout price validation.
    Backend must reject orders where unit_price doesn't match the actual product/batch price.
    """

    def test_pos_order_correct_price_succeeds(self, api_client, retailer_user, product):
        """Normal POS order with correct price should succeed"""
        api_client.force_authenticate(user=retailer_user)
        url = reverse("create_pos_order")
        
        data = {
            "subtotal": float(product.price),
            "total_amount": float(product.price),
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": float(product.price)
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED

    def test_pos_order_wrong_price_rejected(self, api_client, retailer_user, product):
        """POS order with manipulated price should be rejected"""
        api_client.force_authenticate(user=retailer_user)
        url = reverse("create_pos_order")
        
        data = {
            "subtotal": 0.0,
            "total_amount": 0.0,
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": 0.0  # Manipulated price!
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Price mismatch" in response.data.get('error', '')

    def test_pos_order_batch_correct_price_succeeds(self, api_client, retailer_user, retailer, category, brand):
        """POS order with correct batch price should succeed"""
        api_client.force_authenticate(user=retailer_user)

        product = Product.objects.create(
            retailer=retailer, name="Batch Cola", category=category, brand=brand,
            price=Decimal("25.00"), has_batches=True, track_inventory=True, quantity=20
        )
        batch = ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="B1",
            barcode="111222333", price=Decimal("22.00"), quantity=10, is_active=True
        )
        
        url = reverse("create_pos_order")
        data = {
            "subtotal": 22.00,
            "total_amount": 22.00,
            "items": [
                {
                    "product_id": product.id,
                    "batch_id": batch.id,
                    "quantity": 1,
                    "unit_price": 22.00  # Matches batch price
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED

    def test_pos_order_batch_wrong_price_rejected(self, api_client, retailer_user, retailer, category, brand):
        """POS order with manipulated batch price should be rejected"""
        api_client.force_authenticate(user=retailer_user)

        product = Product.objects.create(
            retailer=retailer, name="Batch Cola 2", category=category, brand=brand,
            price=Decimal("25.00"), has_batches=True, track_inventory=True, quantity=20
        )
        batch = ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="B1",
            barcode="444555666", price=Decimal("22.00"), quantity=10, is_active=True
        )
        
        url = reverse("create_pos_order")
        data = {
            "subtotal": 5.00,
            "total_amount": 5.00,
            "items": [
                {
                    "product_id": product.id,
                    "batch_id": batch.id,
                    "quantity": 1,
                    "unit_price": 5.00  # Manipulated - actual is 22.00
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Price mismatch" in response.data.get('error', '')


@pytest.mark.django_db
class TestSyncInventoryConcurrency:
    """
    Tests for sync_inventory_from_batches race condition fix.
    Ensures product correctly aggregates batch quantities with locking.
    """

    def test_sync_inventory_aggregates_correctly(self, retailer, category, brand):
        """Basic sync should correctly sum all active batch quantities"""
        product = Product.objects.create(
            retailer=retailer, name="Sync Rice", category=category, brand=brand,
            price=Decimal("100.00"), has_batches=True, track_inventory=True
        )
        
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="B1",
            price=Decimal("90.00"), original_price=Decimal("100.00"),
            quantity=30, is_active=True, show_on_app=True
        )
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="B2",
            price=Decimal("95.00"), original_price=Decimal("110.00"),
            quantity=20, is_active=True, show_on_app=True
        )
        
        product.sync_inventory_from_batches()
        
        product.refresh_from_db()
        assert product.quantity == 50
        # Best batch (lowest price with stock > 0) should sync
        assert product.price == Decimal("90.00")

    def test_sync_after_reduce_updates_correctly(self, retailer, category, brand):
        """After reducing stock from a batch, parent product total should update"""
        product = Product.objects.create(
            retailer=retailer, name="Reduce Sync Rice", category=category, brand=brand,
            price=Decimal("100.00"), has_batches=True, track_inventory=True
        )
        
        batch = ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="B1",
            price=Decimal("100.00"), quantity=10, is_active=True
        )
        product.sync_inventory_from_batches()
        assert product.quantity == 10
        
        # Simulate POS sale
        product.reduce_quantity(3, batch=batch, allow_negative=True)
        
        product.refresh_from_db()
        batch.refresh_from_db()
        assert batch.quantity == 7
        assert product.quantity == 7


@pytest.mark.django_db
class TestAppPriceFallback:
    """
    Tests for price fallback when all batches go out of stock.
    Customer App pricing should remain up-to-date.
    """

    def test_price_fallback_to_latest_batch_when_all_out_of_stock(self, retailer, category, brand):
        """When all batches are out of stock, price should fallback to latest active batch"""
        product = Product.objects.create(
            retailer=retailer, name="Fallback Price Item", category=category, brand=brand,
            price=Decimal("50.00"), has_batches=True, track_inventory=True
        )
        
        # Old batch (cheaper, created first)
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="OLD",
            price=Decimal("50.00"), original_price=Decimal("60.00"),
            quantity=0, is_active=True, show_on_app=True
        )
        # New batch (pricier, created second) - this is the latest
        new_batch = ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="NEW",
            price=Decimal("55.00"), original_price=Decimal("65.00"),
            quantity=0, is_active=True, show_on_app=True
        )
        
        product.sync_inventory_from_batches()
        product.refresh_from_db()
        
        # All out of stock, so should fallback to latest batch price
        assert product.quantity == 0
        assert product.price == new_batch.price  # 55.00 (latest)
        assert product.original_price == new_batch.original_price  # 65.00

    def test_price_uses_best_batch_when_in_stock(self, retailer, category, brand):
        """When batches have stock, price should use lowest-priced in-stock batch"""
        product = Product.objects.create(
            retailer=retailer, name="Best Price Item", category=category, brand=brand,
            price=Decimal("100.00"), has_batches=True, track_inventory=True
        )
        
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="CHEAP",
            price=Decimal("80.00"), original_price=Decimal("100.00"),
            quantity=5, is_active=True, show_on_app=True
        )
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="EXPENSIVE",
            price=Decimal("95.00"), original_price=Decimal("110.00"),
            quantity=10, is_active=True, show_on_app=True
        )
        
        product.sync_inventory_from_batches()
        product.refresh_from_db()
        
        assert product.quantity == 15
        assert product.price == Decimal("80.00")  # Cheapest in-stock batch


@pytest.mark.django_db
class TestLinkBarcodeBatchCreation:
    """
    Tests for the 'Link to Existing' flow in QuickAddModal.
    Verifies that linking a new barcode creates a proper batch.
    """

    def test_link_barcode_creates_new_batch(self, api_client, retailer_user, retailer, category, brand):
        """Linking a new barcode to an existing product should create a new batch"""
        api_client.force_authenticate(user=retailer_user)
        
        product = Product.objects.create(
            retailer=retailer, name="Link Test Item", category=category, brand=brand,
            price=Decimal("50.00"), barcode="OLD-BARCODE-123",
            quantity=10, track_inventory=True, is_active=True, is_available=True
        )
        # ProductCreateSerializer always creates an INITIAL-STOCK batch
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="INITIAL-STOCK",
            barcode="OLD-BARCODE-123", price=Decimal("50.00"), quantity=10, is_active=True
        )
        
        url = reverse("update_product", args=[product.id])
        data = {
            "link_barcode": "NEW-BARCODE-456",
            "price": 55.00
        }
        
        response = api_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        product.refresh_from_db()
        assert product.has_batches is True
        
        # Should now have 2 active batches
        active_batches = product.batches.filter(is_active=True)
        assert active_batches.count() == 2
        
        # New batch should have the new barcode and 0 stock
        new_batch = active_batches.filter(barcode="NEW-BARCODE-456").first()
        assert new_batch is not None
        assert new_batch.quantity == 0

    def test_link_same_barcode_does_not_duplicate(self, api_client, retailer_user, retailer, category, brand):
        """Linking the same barcode twice should not create duplicate batches"""
        api_client.force_authenticate(user=retailer_user)
        
        product = Product.objects.create(
            retailer=retailer, name="Dup Test Item", category=category, brand=brand,
            price=Decimal("50.00"), barcode="MAIN-BC",
            quantity=10, track_inventory=True, is_active=True, is_available=True
        )
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="INITIAL-STOCK",
            barcode="MAIN-BC", price=Decimal("50.00"), quantity=10, is_active=True
        )
        # Pre-create a batch with the barcode we'll try to link
        ProductBatch.objects.create(
            product=product, retailer=retailer, barcode="EXISTING-BC",
            price=Decimal("55.00"), quantity=5, is_active=True
        )
        
        url = reverse("update_product", args=[product.id])
        data = {
            "link_barcode": "EXISTING-BC",
            "has_batches": True
        }
        
        response = api_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        # Should still be exactly 2, not 3
        product.refresh_from_db()
        assert product.batches.filter(barcode="EXISTING-BC", is_active=True).count() == 1

    def test_link_barcode_to_product_without_barcode(self, api_client, retailer_user, retailer, category, brand):
        """Linking a barcode to a product without existing barcode should set it directly"""
        api_client.force_authenticate(user=retailer_user)
        
        product = Product.objects.create(
            retailer=retailer, name="No BC Item", category=category, brand=brand,
            price=Decimal("30.00"), barcode=None,
            quantity=5, track_inventory=True, is_active=True, is_available=True
        )
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="INITIAL-STOCK",
            barcode=None, price=Decimal("30.00"), quantity=5, is_active=True
        )
        
        url = reverse("update_product", args=[product.id])
        data = {
            "link_barcode": "FIRST-BC-789"
        }
        
        response = api_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        product.refresh_from_db()
        assert product.barcode == "FIRST-BC-789"
        
        # Should NOT have created a new batch, just updated the INITIAL-STOCK one
        initial_batch = product.batches.filter(batch_number="INITIAL-STOCK").first()
        assert initial_batch is not None
        assert initial_batch.barcode == "FIRST-BC-789"


@pytest.mark.django_db
class TestPOSNegativeStockBilling:
    """
    Tests for POS billing when stock is 0 or negative.
    POS must always allow billing (allow_negative=True).
    """

    def test_pos_billing_with_zero_stock(self, api_client, retailer_user, retailer, category, brand):
        """POS should allow billing even when product stock is 0"""
        api_client.force_authenticate(user=retailer_user)

        product = Product.objects.create(
            retailer=retailer, name="Zero Stock Item", category=category, brand=brand,
            price=Decimal("100.00"), quantity=0, track_inventory=True,
            is_active=True, is_available=True
        )
        
        url = reverse("create_pos_order")
        data = {
            "subtotal": 100.00,
            "total_amount": 100.00,
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 2,
                    "unit_price": 100.00
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        product.refresh_from_db()
        assert product.quantity == -2  # Negative stock allowed for POS

    def test_pos_billing_batch_with_zero_stock(self, api_client, retailer_user, retailer, category, brand):
        """POS should allow billing from a batch with 0 stock"""
        api_client.force_authenticate(user=retailer_user)

        product = Product.objects.create(
            retailer=retailer, name="Zero Batch Item", category=category, brand=brand,
            price=Decimal("75.00"), has_batches=True, track_inventory=True, quantity=0
        )
        batch = ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="EMPTY",
            barcode="EMPTY-BC", price=Decimal("75.00"), quantity=0, is_active=True
        )
        
        url = reverse("create_pos_order")
        data = {
            "subtotal": 75.00,
            "total_amount": 75.00,
            "items": [
                {
                    "product_id": product.id,
                    "batch_id": batch.id,
                    "quantity": 1,
                    "unit_price": 75.00
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        batch.refresh_from_db()
        assert batch.quantity == -1  # Negative allowed


@pytest.mark.django_db
class TestProductUpdateConcurrency:
    """
    Tests for product update concurrency safety (select_for_update).
    """

    def test_update_product_with_inventory_log(self, api_client, retailer_user, product):
        """Product update should correctly log inventory changes"""
        api_client.force_authenticate(user=retailer_user)
        old_qty = product.quantity
        
        url = reverse("update_product", args=[product.id])
        data = {"quantity": old_qty + 10}
        
        response = api_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        product.refresh_from_db()
        assert product.quantity == old_qty + 10
        
        # Verify inventory log was created
        log = ProductInventoryLog.objects.filter(
            product=product, reason='Product update'
        ).last()
        assert log is not None
        assert log.quantity_change == 10
        assert log.log_type == 'added'

    def test_update_product_price_change(self, api_client, retailer_user, product):
        """Product price update should work correctly with locking"""
        api_client.force_authenticate(user=retailer_user)
        
        url = reverse("update_product", args=[product.id])
        data = {"price": 120.00}
        
        response = api_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        product.refresh_from_db()
        assert product.price == Decimal("120.00")
