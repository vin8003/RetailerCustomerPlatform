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
