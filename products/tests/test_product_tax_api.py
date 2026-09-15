from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from authentication.models import User
from products.models import Product, ProductBrand, ProductCategory
from products.serializers import (
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductUpdateSerializer,
)
from products.views import process_excel_upload
from retailers.models import RetailerProfile


class ProductTaxSerializerTests(TestCase):
    def setUp(self):
        self.retailer_user = User.objects.create_user(
            username="tax_retailer",
            email="tax_retailer@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        self.retailer = RetailerProfile.objects.create(
            user=self.retailer_user,
            shop_name="Tax Test Shop",
            address_line1="123 Main St",
            city="TestCity",
            state="TestState",
            pincode="123456",
            is_active=True,
        )
        self.category = ProductCategory.objects.create(
            name="Groceries", retailer=self.retailer
        )
        self.brand = ProductBrand.objects.create(name="TestBrand")
        self.product = Product.objects.create(
            retailer=self.retailer,
            name="Test Rice 5kg",
            category=self.category,
            brand=self.brand,
            price=Decimal("90.00"),
            original_price=Decimal("100.00"),
            quantity=50,
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="kg",
        )

    def test_product_serializers_expose_and_validate_tax_fields(self):
        self.product.hsn_code = "21069099"
        self.product.gst_rate = Decimal("5")
        self.product.save(update_fields=["hsn_code", "gst_rate"])

        self.assertEqual(
            ProductListSerializer(self.product).data["hsn_code"], "21069099"
        )
        self.assertEqual(
            ProductListSerializer(self.product).data["gst_rate"], "5.00"
        )
        self.assertEqual(
            ProductDetailSerializer(self.product).data["hsn_code"], "21069099"
        )
        self.assertEqual(
            ProductDetailSerializer(self.product).data["gst_rate"], "5.00"
        )

        create_serializer = ProductCreateSerializer(
            data={
                "name": "Taxed Product",
                "price": "100.00",
                "quantity": 1,
                "hsn_code": "21069099",
                "gst_rate": "18",
            },
            context={"retailer": self.retailer},
        )
        self.assertTrue(create_serializer.is_valid(), create_serializer.errors)

        for serializer in (
            ProductCreateSerializer(
                data={
                    "name": "Bad Tax",
                    "price": "10.00",
                    "quantity": 1,
                    "gst_rate": "12",
                },
                context={"retailer": self.retailer},
            ),
            ProductUpdateSerializer(
                self.product, data={"gst_rate": "12"}, partial=True
            ),
        ):
            self.assertFalse(serializer.is_valid())
            self.assertIn("gst_rate", serializer.errors)


class ProductTaxAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.retailer_user = User.objects.create_user(
            username="tax_api_retailer",
            email="tax_api_retailer@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        self.retailer = RetailerProfile.objects.create(
            user=self.retailer_user,
            shop_name="Tax API Shop",
            address_line1="123 Main St",
            city="TestCity",
            state="TestState",
            pincode="123456",
            is_active=True,
        )
        self.category = ProductCategory.objects.create(
            name="Groceries", retailer=self.retailer
        )
        self.brand = ProductBrand.objects.create(name="TestBrand")
        self.product = Product.objects.create(
            retailer=self.retailer,
            name="Test Rice 5kg",
            category=self.category,
            brand=self.brand,
            price=Decimal("90.00"),
            original_price=Decimal("100.00"),
            quantity=50,
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="kg",
        )
        self.client.force_authenticate(user=self.retailer_user)

    def test_create_product_api_accepts_tax_fields(self):
        response = self.client.post(
            reverse("create_product"),
            {
                "name": "GST Product",
                "price": "100.00",
                "quantity": 2,
                "hsn_code": "21069099",
                "gst_rate": "18",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["hsn_code"], "21069099")
        self.assertEqual(response.data["gst_rate"], "18.00")
        product = Product.objects.get(name="GST Product", retailer=self.retailer)
        self.assertEqual(product.hsn_code, "21069099")
        self.assertEqual(product.gst_rate, Decimal("18"))

    def test_bulk_update_accepts_tax_fields(self):
        response = self.client.patch(
            reverse("bulk_update_products"),
            {
                "items": [
                    {"id": self.product.id, "hsn_code": "21069099", "gst_rate": "5"}
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.hsn_code, "21069099")
        self.assertEqual(self.product.gst_rate, Decimal("5"))

    def test_bulk_update_rejects_unsupported_gst_rate(self):
        response = self.client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": self.product.id, "gst_rate": "12"}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.product.refresh_from_db()
        self.assertEqual(self.product.gst_rate, Decimal("0"))

    def test_bulk_update_skips_none_hsn_code(self):
        self.product.hsn_code = "21069099"
        self.product.save(update_fields=["hsn_code"])

        response = self.client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": self.product.id, "hsn_code": None}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.hsn_code, "21069099")


class ProductTaxExcelTests(TestCase):
    def setUp(self):
        self.retailer_user = User.objects.create_user(
            username="tax_excel_retailer",
            email="tax_excel_retailer@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        self.retailer = RetailerProfile.objects.create(
            user=self.retailer_user,
            shop_name="Tax Excel Shop",
            address_line1="123 Main St",
            city="TestCity",
            state="TestState",
            pincode="123456",
            is_active=True,
        )

    def test_excel_tax_columns_are_optional_and_blank_defaults_to_zero(self):
        csv_file = SimpleUploadedFile(
            "products.csv",
            (
                b"name,price,quantity,hsn,gst_rate\n"
                b"Taxed Excel Product,100,2,21069099,18\n"
                b"Untaxed Excel Product,50,1,,\n"
            ),
            content_type="text/csv",
        )

        result = process_excel_upload(csv_file, self.retailer, self.retailer_user)

        self.assertEqual(result["successful_rows"], 2)
        taxed = Product.objects.get(name="Taxed Excel Product")
        untaxed = Product.objects.get(name="Untaxed Excel Product")
        self.assertEqual(taxed.hsn_code, "21069099")
        self.assertEqual(taxed.gst_rate, Decimal("18"))
        self.assertEqual(untaxed.hsn_code, "")
        self.assertEqual(untaxed.gst_rate, Decimal("0"))

    def test_excel_rejects_unsupported_nonblank_gst_rate(self):
        csv_file = SimpleUploadedFile(
            "products.csv",
            b"name,price,quantity,gst_rate\nBad Tax Product,100,2,12\n",
            content_type="text/csv",
        )

        result = process_excel_upload(csv_file, self.retailer, self.retailer_user)

        self.assertEqual(result["successful_rows"], 0)
        self.assertEqual(result["failed_rows"], 1)
        self.assertIn("Unsupported GST rate", result["error_log"][0]["error"])
        self.assertFalse(Product.objects.filter(name="Bad Tax Product").exists())

    def test_excel_reupload_preserves_blank_tax_columns(self):
        Product.objects.create(
            retailer=self.retailer,
            name="Existing Tax Product",
            price=Decimal("100.00"),
            quantity=5,
            hsn_code="21069099",
            gst_rate=Decimal("18"),
            unit="piece",
        )

        csv_file = SimpleUploadedFile(
            "products.csv",
            b"name,price,quantity,hsn,gst_rate\nExisting Tax Product,100,5,,\n",
            content_type="text/csv",
        )

        result = process_excel_upload(csv_file, self.retailer, self.retailer_user)

        self.assertEqual(result["successful_rows"], 1)
        product = Product.objects.get(name="Existing Tax Product", retailer=self.retailer)
        self.assertEqual(product.hsn_code, "21069099")
        self.assertEqual(product.gst_rate, Decimal("18"))
