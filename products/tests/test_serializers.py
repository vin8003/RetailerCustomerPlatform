import pytest
from decimal import Decimal
from products.serializers import (
    ProductCategorySerializer, ProductListSerializer, 
    ProductDetailSerializer, ProductCreateSerializer,
    ProductUpdateSerializer, ProductBulkUploadSerializer
)
from products.models import ProductReview, ProductImage
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
