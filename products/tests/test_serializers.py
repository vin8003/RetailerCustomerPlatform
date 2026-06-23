import pytest
from decimal import Decimal
from products.serializers import (
    ProductCategorySerializer, ProductListSerializer, 
    ProductDetailSerializer, ProductCreateSerializer,
    ProductUpdateSerializer, ProductBulkUploadSerializer,
    PurchaseInvoiceSerializer, SupplierLedgerSerializer
)
from products.models import Product, ProductReview, ProductImage
from django.core.files.uploadedfile import SimpleUploadedFile


@pytest.mark.django_db
class TestProductCategorySerializer:
    def test_get_subcategories(self, category, subcategory):
        serializer = ProductCategorySerializer(category)
        data = serializer.data
        assert len(data["subcategories"]) == 1
        assert data["subcategories"][0]["name"] == "Snacks"


@pytest.mark.django_db
class TestProductListSerializer:
    def test_list_serialization(self, product, category, brand):
        serializer = ProductListSerializer(product)
        data = serializer.data
        assert data["name"] == "Test Rice 5kg"
        assert data["category_name"] == "Groceries"
        assert data["brand_name"] == "TestBrand"
        assert float(data["price"]) == 90.00
        assert data["is_in_stock"] is True

    def test_active_offer_text(self, product, offer):
        # Without context
        serializer = ProductListSerializer(product)
        assert serializer.data["active_offer_text"] == "Rice Discount"
        
        # With context (optimized path)
        serializer = ProductListSerializer(product, context={"active_offers": [offer]})
        assert serializer.data["active_offer_text"] == "Rice Discount"

    def test_is_wishlisted(self, product, customer, wishlist_item):
        # Mock request context
        from unittest.mock import MagicMock
        request = MagicMock()
        request.user = customer
        
        serializer = ProductListSerializer(product, context={"request": request})
        assert serializer.data["is_wishlisted"] is True

    def test_average_rating(self, product, customer):
        ProductReview.objects.create(product=product, customer=customer, rating=4)
        serializer = ProductListSerializer(product)
        assert serializer.data["average_rating"] == 4.0


@pytest.mark.django_db
class TestProductDetailSerializer:
    def test_detail_serialization(self, product):
        serializer = ProductDetailSerializer(product)
        data = serializer.data
        assert data["name"] == "Test Rice 5kg"
        assert "category" in data
        assert "brand" in data

    def test_get_images_unified(self, product):
        # 1. URL fallback
        product.image_url = "http://example.com/p1.jpg"
        product.save()
        
        serializer = ProductDetailSerializer(product)
        assert "http://example.com/p1.jpg" in serializer.data["images"]
        
        # 2. Additional Image (valid mapping)
        minimal_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        product_img = ProductImage.objects.create(
            product=product, 
            image=SimpleUploadedFile("img.gif", minimal_gif, content_type="image/gif")
        )
        
        serializer = ProductDetailSerializer(product)
        images = serializer.data["images"]
        assert len(images) == 2
        assert any("http://example.com/p1.jpg" == img for img in images)
        # Check for the existence of the uploaded image (UUID name)
        assert any("uploads/productimage" in img for img in images)

    def test_get_group_variants_sorting(self, product, retailer, category):
        # Current product has product_group="grain"
        product.product_group = "grain"
        product.save()
        
        # Create normal sibling
        normal_sibling = Product.objects.create(
            retailer=retailer,
            name="Normal Sibling",
            price=Decimal("50.00"),
            category=category,
            product_group="grain",
            is_active=True,
            is_available=True
        )
        
        # Create parent sibling
        parent_sibling = Product.objects.create(
            retailer=retailer,
            name="Parent Sibling",
            price=Decimal("100.00"),
            category=category,
            product_group="grain",
            is_parent_bulk=True,
            is_active=True,
            is_available=True
        )
        
        # Create child sibling
        child_sibling = Product.objects.create(
            retailer=retailer,
            name="Child Sibling",
            price=Decimal("10.00"),
            category=category,
            product_group="grain",
            parent_bulk_product=parent_sibling,
            conversion_factor=Decimal("10"),
            is_active=True,
            is_available=True
        )
        
        # Serialize current product
        serializer = ProductDetailSerializer(product)
        group_variants = serializer.data["group_variants"]
        
        # Sibling variants list should not contain the current product itself
        variant_ids = [v["id"] for v in group_variants]
        assert product.id not in variant_ids
        assert len(variant_ids) == 3
        
        # Parent and child should be before normal
        normal_idx = variant_ids.index(normal_sibling.id)
        parent_idx = variant_ids.index(parent_sibling.id)
        child_idx = variant_ids.index(child_sibling.id)
        
        assert parent_idx < normal_idx
        assert child_idx < normal_idx
        
        # Verify fields in variant representation
        assert "image" in group_variants[0]
        assert "minimum_order_quantity" in group_variants[0]
        assert "track_inventory" in group_variants[0]


@pytest.mark.django_db
class TestProductCreateUpdateSerializers:
    def test_create_validation_price(self, retailer, category):
        data = {
            "name": "Invalid Price",
            "price": "100.00",
            "original_price": "90.00", # Invalid: original < price
            "category": category.id,
            "quantity": 10
        }
        serializer = ProductCreateSerializer(data=data, context={"retailer": retailer})
        assert not serializer.is_valid()
        assert "original_price" in serializer.errors or "non_field_errors" in serializer.errors

    def test_create_validation_quantity(self, retailer, category):
        data = {
            "name": "Invalid Qty",
            "price": "10.00",
            "quantity": 5,
            "minimum_order_quantity": 10, # Invalid: min > qty
            "category": category.id
        }
        serializer = ProductCreateSerializer(data=data, context={"retailer": retailer})
        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors

    def test_update_validation(self, product):
        data = {"minimum_order_quantity": 60} # product.quantity is 50
        serializer = ProductUpdateSerializer(product, data=data, partial=True)
        assert not serializer.is_valid()


class TestProductBulkUploadSerializer:
    def test_validate_file_extension(self):
        file = SimpleUploadedFile("test.txt", b"content")
        serializer = ProductBulkUploadSerializer(data={"file": file})
        assert not serializer.is_valid()
        assert "file" in serializer.errors

    def test_validate_file_size(self):
        # 11MB file
        file = SimpleUploadedFile("test.xlsx", b"0" * (11 * 1024 * 1024))
        serializer = ProductBulkUploadSerializer(data={"file": file})
        assert not serializer.is_valid()
        assert "file" in serializer.errors


@pytest.mark.django_db
class TestPurchaseInvoiceSerializer:
    def test_purchase_invoice_validation_without_retailer(self, retailer, product):
        from retailers.models import Supplier
        supplier = Supplier.objects.create(retailer=retailer, company_name="Test Supplier")
        
        data = {
            "supplier": supplier.id,
            "invoice_number": "TEST-INV-123",
            "invoice_date": "2026-06-16",
            "total_amount": "100.00",
            "paid_amount": "0.00",
            "payment_status": "UNPAID",
            "items": [
                {
                    "product": product.id,
                    "quantity": 10,
                    "purchase_price": "10.00",
                    "total": "100.00",
                    "new_price": "12.00",
                    "new_original_price": "15.00",
                    "mrp_updated": True
                }
            ]
        }
        
        # Validating without sending 'retailer' in data should be valid because 'retailer' is read-only
        serializer = PurchaseInvoiceSerializer(data=data, context={"retailer": retailer})
        assert serializer.is_valid(), serializer.errors
        
    def test_purchase_invoice_ledger_creation_no_duplicates(self, retailer, product):
        from retailers.models import Supplier
        from products.models import SupplierLedger
        from unittest.mock import MagicMock
        
        supplier = Supplier.objects.create(retailer=retailer, company_name="Test Supplier")
        
        data = {
            "supplier": supplier.id,
            "invoice_number": "TEST-INV-DUPE",
            "invoice_date": "2026-06-16",
            "total_amount": "200.00",
            "paid_amount": "50.00",
            "payment_status": "PARTIAL",
            "items": [
                {
                    "product": product.id,
                    "quantity": 10,
                    "purchase_price": "10.00",
                    "total": "100.00"
                },
                {
                    "product": product.id,
                    "quantity": 10,
                    "purchase_price": "10.00",
                    "total": "100.00"
                }
            ]
        }
        
        # Mock request with user
        request = MagicMock()
        request.user = retailer.user
        
        serializer = PurchaseInvoiceSerializer(data=data, context={"request": request, "retailer": retailer})
        assert serializer.is_valid(), serializer.errors
        
        invoice = serializer.save(retailer=retailer)
        
        # Check SupplierLedger entries
        credit_entries = SupplierLedger.objects.filter(reference_invoice=invoice, transaction_type="CREDIT")
        debit_entries = SupplierLedger.objects.filter(reference_invoice=invoice, transaction_type="DEBIT")
        
        # Should only have 1 Credit and 1 Debit entry, despite having 2 items in invoice!
        assert credit_entries.count() == 1
        assert credit_entries.first().amount == Decimal("200.00")
        assert debit_entries.count() == 1
        assert debit_entries.first().amount == Decimal("50.00")


@pytest.mark.django_db
class TestSupplierLedgerSerializer:
    def test_supplier_ledger_serialization_with_and_without_invoice(self, retailer):
        from retailers.models import Supplier
        from products.models import SupplierLedger
        
        supplier = Supplier.objects.create(retailer=retailer, company_name="Test Supplier Ledger")
        
        # 1. Create a ledger entry without an invoice
        ledger_no_inv = SupplierLedger.objects.create(
            supplier=supplier,
            date="2026-06-24",
            amount=Decimal("150.00"),
            transaction_type="DEBIT",
            notes="General Payment"
        )
        
        # This serialization should NOT raise AttributeError
        serializer = SupplierLedgerSerializer(ledger_no_inv)
        assert serializer.data["reference_invoice_number"] is None
        
        # 2. Create a ledger entry with an invoice
        from products.models import PurchaseInvoice
        invoice = PurchaseInvoice.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice_number="INV-12345",
            invoice_date="2026-06-24",
            total_amount=Decimal("150.00")
        )
        ledger_with_inv = SupplierLedger.objects.create(
            supplier=supplier,
            date="2026-06-24",
            amount=Decimal("150.00"),
            transaction_type="CREDIT",
            reference_invoice=invoice,
            notes="Credit for invoice"
        )
        
        serializer_with_inv = SupplierLedgerSerializer(ledger_with_inv)
        assert serializer_with_inv.data["reference_invoice_number"] == "INV-12345"

