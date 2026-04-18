import pytest
from decimal import Decimal
from products.models import (
    Product, ProductCategory, ProductBrand, ProductReview,
    ProductInventoryLog, MasterProduct, ProductImage,
    ProductUpload, ProductUploadSession, UploadSessionItem,
    SearchTelemetry, MasterProductImage,
)


@pytest.mark.django_db
class TestProductCategory:

    def test_str(self, category):
        assert str(category) == "Groceries"

    def test_subcategory(self, subcategory, category):
        assert subcategory.parent == category
        assert category.subcategories.count() == 1


@pytest.mark.django_db
class TestProductBrand:

    def test_str(self, brand):
        assert str(brand) == "TestBrand"


@pytest.mark.django_db
class TestMasterProduct:

    def test_str(self, master_product):
        assert "Master Rice Product" in str(master_product)
        assert "8901234567890" in str(master_product)


@pytest.mark.django_db
class TestProduct:

    def test_str(self, product):
        assert "Test Rice 5kg" in str(product)
        assert "Products Test Shop" in str(product)

    def test_discount_percentage_calculated(self, product):
        # original_price=100, price=90 → 10%
        assert product.discount_percentage == Decimal("10.00")

    def test_no_discount_when_prices_equal(self, retailer, category, brand):
        p = Product.objects.create(
            retailer=retailer,
            name="No Discount",
            category=category,
            brand=brand,
            price=Decimal("100.00"),
            original_price=Decimal("100.00"),
            quantity=5,
            is_active=True,
        )
        assert p.discount_percentage == Decimal("0.00")

    def test_is_in_stock_tracked(self, product):
        assert product.is_in_stock is True
        product.quantity = 0
        assert product.is_in_stock is False

    def test_is_in_stock_untracked(self, retailer, category, brand):
        p = Product.objects.create(
            retailer=retailer,
            name="Untracked",
            category=category,
            brand=brand,
            price=Decimal("10.00"),
            track_inventory=False,
            is_available=True,
            is_active=True,
        )
        assert p.is_in_stock is True
        p.is_available = False
        assert p.is_in_stock is False

    def test_image_display_url_fallback(self, product, master_product):
        # No image, no image_url → None
        assert product.image_display_url is None

        product.image_url = "https://example.com/img.jpg"
        assert product.image_display_url == "https://example.com/img.jpg"

        product.image_url = ""
        product.master_product = master_product
        master_product.image_url = "https://example.com/master.jpg"
        master_product.save()
        assert product.image_display_url == "https://example.com/master.jpg"

    def test_discounted_price(self, product):
        assert product.discounted_price == product.price

    def test_savings(self, product):
        assert product.savings == Decimal("10.00")

    def test_savings_no_discount(self, product2):
        assert product2.savings == Decimal("0.00")

    def test_can_order_quantity(self, product):
        assert product.can_order_quantity(5) is True
        assert product.can_order_quantity(0) is False  # below min
        assert product.can_order_quantity(11) is False  # above max
        assert product.can_order_quantity(51) is False  # above stock

    def test_can_order_untracked(self, retailer, category, brand):
        p = Product.objects.create(
            retailer=retailer,
            name="Untracked Order",
            category=category,
            brand=brand,
            price=Decimal("10.00"),
            track_inventory=False,
            is_available=True,
            is_active=True,
        )
        assert p.can_order_quantity(100) is True

    def test_reduce_quantity(self, product):
        product.reduce_quantity(5)
        product.refresh_from_db()
        assert product.quantity == 45

    def test_reduce_quantity_insufficient(self, product):
        result = product.reduce_quantity(100)
        assert result is False

    def test_reduce_quantity_untracked(self, retailer, category, brand):
        p = Product.objects.create(
            retailer=retailer,
            name="Untracked Reduce",
            category=category,
            brand=brand,
            price=Decimal("10.00"),
            track_inventory=False,
            is_active=True,
        )
        assert p.reduce_quantity(100) is True

    def test_increase_quantity(self, product):
        product.increase_quantity(10)
        product.refresh_from_db()
        assert product.quantity == 60

    def test_increase_quantity_untracked(self, retailer, category, brand):
        p = Product.objects.create(
            retailer=retailer,
            name="Untracked Increase",
            category=category,
            brand=brand,
            price=Decimal("10.00"),
            track_inventory=False,
            is_active=True,
        )
        assert p.increase_quantity(10) is True


@pytest.mark.django_db
class TestProductReview:

    def test_str(self, product, customer):
        review = ProductReview.objects.create(
            product=product,
            customer=customer,
            rating=4,
            title="Good product",
            comment="I liked it",
        )
        assert "Test Rice 5kg" in str(review)
        assert "4 stars" in str(review)


@pytest.mark.django_db
class TestProductInventoryLog:

    def test_str(self, product, retailer_user):
        log = ProductInventoryLog.objects.create(
            product=product,
            log_type="added",
            quantity_change=10,
            previous_quantity=50,
            new_quantity=60,
            reason="Restock",
            created_by=retailer_user,
        )
        assert "Test Rice 5kg" in str(log)
        assert "added" in str(log)


@pytest.mark.django_db
class TestProductUploadModels:

    def test_upload_str(self, retailer):
        upload = ProductUpload.objects.create(
            retailer=retailer,
            file="test.xlsx",
        )
        assert "Products Test Shop" in str(upload)

    def test_upload_session_str(self, retailer):
        session = ProductUploadSession.objects.create(retailer=retailer)
        assert "Products Test Shop" in str(session)

    def test_upload_session_item_str(self, retailer):
        session = ProductUploadSession.objects.create(retailer=retailer)
        item = UploadSessionItem.objects.create(
            session=session,
            barcode="123456",
        )
        assert "123456" in str(item)


@pytest.mark.django_db
class TestSearchTelemetry:

    def test_str(self, retailer):
        t = SearchTelemetry.objects.create(
            retailer=retailer,
            query="rice",
            result_count=5,
        )
        assert "rice" in str(t)
        assert "5 results" in str(t)


@pytest.mark.django_db
class TestMasterProductImage:

    def test_str(self, master_product):
        img = MasterProductImage.objects.create(
            master_product=master_product,
            image_url="https://example.com/img.jpg",
        )
        assert "Master Rice Product" in str(img)
