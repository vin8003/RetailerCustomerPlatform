import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from products.models import Product, ProductBatch
from products.serializers import ProductUpdateSerializer

@pytest.mark.django_db
class TestProductGrouping:
    @pytest.fixture
    def setup_catalog(self, retailer, category, brand):
        """Setup a parent bulk product and a child fractional product"""
        parent = Product.objects.create(
            retailer=retailer,
            name="Premium Rice 50kg Bag",
            price=Decimal("2000.00"),
            quantity=Decimal("10.000"),
            category=category,
            brand=brand,
            is_parent_bulk=True,
            track_inventory=True
        )
        
        # Create initial batch for parent
        ProductBatch.objects.create(
            product=parent,
            retailer=retailer,
            batch_number="PARENT-BATCH-1",
            price=parent.price,
            quantity=parent.quantity,
            is_active=True
        )
        
        child = Product.objects.create(
            retailer=retailer,
            name="Premium Rice 5kg Bag",
            price=Decimal("250.00"),
            quantity=Decimal("0.000"),
            category=category,
            brand=brand,
            is_parent_bulk=False,
            parent_bulk_product=parent,
            conversion_factor=Decimal("0.1000"), # 5kg is 0.1 of 50kg
            track_inventory=True
        )
        
        # Create initial batch for child
        ProductBatch.objects.create(
            product=child,
            retailer=retailer,
            batch_number="CHILD-BATCH-1",
            price=child.price,
            quantity=child.quantity,
            is_active=True
        )
        
        return parent, child

    def test_initial_stock_synchronization(self, setup_catalog):
        """Test child quantity is automatically calculated and set from parent bulk stock"""
        parent, child = setup_catalog
        
        # Child quantity should be parent.quantity / conversion_factor
        # 10.000 / 0.1000 = 100.000
        assert child.quantity == Decimal("100.000")
        
        # Update parent stock
        parent.quantity = Decimal("15.000")
        parent.save()
        
        child.refresh_from_db()
        # 15.000 / 0.1000 = 150.000
        assert child.quantity == Decimal("150.000")

    def test_can_order_quantity_checking(self, setup_catalog):
        """Test child can_order_quantity delegates to parent capability checking"""
        parent, child = setup_catalog
        
        # Child has 100 available. Ordering 50 is fine.
        assert child.can_order_quantity(Decimal("50.000")) is True
        
        # Ordering 120 is too much (120 * 0.10 = 12 bags needed, but parent only has 10)
        assert child.can_order_quantity(Decimal("120.000")) is False

    def test_proportional_stock_deduction(self, setup_catalog):
        """Test that purchasing a child SKU deducts stock proportionally from the parent bulk stock"""
        parent, child = setup_catalog
        
        # Reduce child quantity by 10 (needs 10 * 0.10 = 1 parent bag)
        success = child.reduce_quantity(Decimal("10.000"))
        assert success is True
        
        parent.refresh_from_db()
        child.refresh_from_db()
        
        # Parent stock should be 10 - 1 = 9
        assert parent.quantity == Decimal("9.000")
        # Child stock should be synced to 9 / 0.10 = 90
        assert child.quantity == Decimal("90.000")

    def test_proportional_stock_restoration(self, setup_catalog):
        """Test that canceling/returning a child SKU restores stock proportionally to parent"""
        parent, child = setup_catalog
        
        # Deduct child quantity by 10
        child.reduce_quantity(Decimal("10.000"))
        
        # Restore child quantity by 5 (gives back 5 * 0.10 = 0.5 parent bag)
        success = child.increase_quantity(Decimal("5.000"))
        assert success is True
        
        parent.refresh_from_db()
        child.refresh_from_db()
        
        # Parent should be 9 + 0.5 = 9.5
        assert parent.quantity == Decimal("9.500")
        # Child should be 9.5 / 0.1 = 95
        assert child.quantity == Decimal("95.000")

    def test_cascading_deletion_safety(self, setup_catalog):
        """Test deleting a parent product does not delete child products, but sets relation to NULL"""
        parent, child = setup_catalog
        
        parent_id = parent.id
        child_id = child.id
        
        parent.delete()
        
        # Verify child is not deleted, but parent_bulk_product is set to NULL
        child_restored = Product.objects.get(id=child_id)
        assert child_restored.parent_bulk_product is None

    def test_transition_safety_stock_check(self, retailer, category, brand):
        """Test serializer prevents establishing a grouping link if the child product has positive inventory"""
        standalone = Product.objects.create(
            retailer=retailer,
            name="Standalone Rice 5kg Bag",
            price=Decimal("250.00"),
            quantity=Decimal("20.000"), # Active stock
            category=category,
            brand=brand,
            track_inventory=True
        )
        
        parent = Product.objects.create(
            retailer=retailer,
            name="Standalone Rice 50kg Bag",
            price=Decimal("2000.00"),
            quantity=Decimal("10.000"),
            category=category,
            brand=brand,
            is_parent_bulk=True,
            track_inventory=True
        )
        
        # Attempt to link standalone to parent while it has stock
        serializer = ProductUpdateSerializer(
            instance=standalone,
            data={
                "parent_bulk_product": parent.id,
                "conversion_factor": "0.1000"
            },
            partial=True
        )
        
        # Shoule raise DRF validation error
        with pytest.raises(DRFValidationError) as excinfo:
            serializer.is_valid(raise_exception=True)
        
        assert "This product has active inventory" in str(excinfo.value)
        
        # Reset stock to 0 and verify link succeeds
        standalone.quantity = Decimal("0.000")
        standalone.save()
        
        serializer = ProductUpdateSerializer(
            instance=standalone,
            data={
                "parent_bulk_product": parent.id,
                "conversion_factor": "0.1000"
            },
            partial=True
        )
        assert serializer.is_valid() is True

    def test_cross_retailer_grouping_validation(self, retailer, category, brand):
        """Test that serializers prevent linking products across different retailers"""
        from retailers.models import RetailerProfile
        from django.contrib.auth import get_user_model
        
        User = get_user_model()
        other_user = User.objects.create_user(
            username="other_retailer_user",
            email="other@test.com",
            password="password123"
        )
        
        other_retailer = RetailerProfile.objects.create(
            user=other_user,
            shop_name="Other Store",
            is_active=True
        )
        
        other_parent = Product.objects.create(
            retailer=other_retailer,
            name="Other Parent 50kg Bag",
            price=Decimal("2000.00"),
            quantity=Decimal("10.000"),
            category=category,
            brand=brand,
            is_parent_bulk=True,
            track_inventory=True
        )
        
        standalone = Product.objects.create(
            retailer=retailer,
            name="My Child 5kg Bag",
            price=Decimal("250.00"),
            quantity=Decimal("0.000"),
            category=category,
            brand=brand,
            track_inventory=True
        )
        
        # Test validation on update
        serializer = ProductUpdateSerializer(
            instance=standalone,
            data={
                "parent_bulk_product": other_parent.id,
                "conversion_factor": "0.1000"
            },
            partial=True,
            context={"retailer": retailer}
        )
        
        with pytest.raises(DRFValidationError) as excinfo:
            serializer.is_valid(raise_exception=True)
            
        assert "Parent bulk product must belong to the same retailer." in str(excinfo.value)

    def test_child_batch_parameter_ignored_on_delegation(self, setup_catalog):
        """Test that when child quantity methods are called with a batch parameter, the child batch is NOT passed to the parent (preventing silent drift)"""
        parent, child = setup_catalog
        
        # Setup parent to use batches and child to have a batch
        parent.has_batches = True
        parent.save()
        
        # Clear old parent batches to ensure our new batch is the FIFO target
        parent.batches.all().delete()
        
        # Create a real batch for parent
        parent_batch = ProductBatch.objects.create(
            product=parent,
            retailer=parent.retailer,
            batch_number="PARENT-BATCH-FIFO",
            price=parent.price,
            quantity=Decimal("10.000"),
            is_active=True
        )
        parent.sync_inventory_from_batches()
        
        # Create a virtual batch for child
        child_batch = ProductBatch.objects.create(
            product=child,
            retailer=child.retailer,
            batch_number="CHILD-BATCH-VIRTUAL",
            price=child.price,
            quantity=Decimal("100.000"),
            is_active=True
        )
        child.sync_inventory_from_batches()
        
        # Call child's reduce_quantity with child's virtual batch
        # This will delegate reduction to parent.
        # Since child's batch is passed as parameter, parent should ignore it (i.e. use FIFO instead of child's batch)
        success = child.reduce_quantity(Decimal("10.000"), batch=child_batch)
        assert success is True
        
        parent_batch.refresh_from_db()
        child_batch.refresh_from_db()
        parent.refresh_from_db()
        child.refresh_from_db()
        
        # Parent's batch should be reduced from 10 to 9 via FIFO (because child_batch was ignored)
        assert parent_batch.quantity == Decimal("9.000")
        assert parent.quantity == Decimal("9.000")
        
        # Child's virtual batch should be unaffected directly (its overall quantity is synced from parent)
        # Sibling inventory sync will update child's quantity to 90.
        assert child.quantity == Decimal("90.000")
