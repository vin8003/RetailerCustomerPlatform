from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status

from products.models import Product
from products.serializers import (
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductUpdateSerializer,
)
from products.views import process_excel_upload


@pytest.mark.django_db
def test_product_serializers_expose_and_validate_tax_fields(product, retailer):
    product.hsn_code = "21069099"
    product.gst_rate = Decimal("5")
    product.save(update_fields=["hsn_code", "gst_rate"])

    assert ProductListSerializer(product).data["hsn_code"] == "21069099"
    assert ProductListSerializer(product).data["gst_rate"] == "5.00"
    assert ProductDetailSerializer(product).data["hsn_code"] == "21069099"
    assert ProductDetailSerializer(product).data["gst_rate"] == "5.00"

    create_serializer = ProductCreateSerializer(
        data={
            "name": "Taxed Product",
            "price": "100.00",
            "quantity": 1,
            "hsn_code": "21069099",
            "gst_rate": "18",
        },
        context={"retailer": retailer},
    )
    assert create_serializer.is_valid(), create_serializer.errors

    for serializer in (
        ProductCreateSerializer(
            data={"name": "Bad Tax", "price": "10.00", "quantity": 1, "gst_rate": "12"},
            context={"retailer": retailer},
        ),
        ProductUpdateSerializer(product, data={"gst_rate": "12"}, partial=True),
    ):
        assert not serializer.is_valid()
        assert "gst_rate" in serializer.errors


@pytest.mark.django_db
def test_create_product_api_accepts_tax_fields(api_client, retailer_user, retailer):
    api_client.force_authenticate(user=retailer_user)

    response = api_client.post(
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

    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert response.data["hsn_code"] == "21069099"
    assert response.data["gst_rate"] == "18.00"
    product = Product.objects.get(name="GST Product", retailer=retailer)
    assert product.hsn_code == "21069099"
    assert product.gst_rate == Decimal("18")


@pytest.mark.django_db
def test_bulk_update_accepts_tax_fields(api_client, retailer_user, product):
    api_client.force_authenticate(user=retailer_user)

    response = api_client.patch(
        reverse("bulk_update_products"),
        {"items": [{"id": product.id, "hsn_code": "21069099", "gst_rate": "5"}]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.data
    product.refresh_from_db()
    assert product.hsn_code == "21069099"
    assert product.gst_rate == Decimal("5")


@pytest.mark.django_db
def test_bulk_update_rejects_unsupported_gst_rate(api_client, retailer_user, product):
    api_client.force_authenticate(user=retailer_user)

    response = api_client.patch(
        reverse("bulk_update_products"),
        {"items": [{"id": product.id, "gst_rate": "12"}]},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    product.refresh_from_db()
    assert product.gst_rate == Decimal("0")


@pytest.mark.django_db
def test_excel_tax_columns_are_optional_and_blank_defaults_to_zero(retailer, retailer_user):
    csv_file = SimpleUploadedFile(
        "products.csv",
        (
            b"name,price,quantity,hsn,gst_rate\n"
            b"Taxed Excel Product,100,2,21069099,18\n"
            b"Untaxed Excel Product,50,1,,\n"
        ),
        content_type="text/csv",
    )

    result = process_excel_upload(csv_file, retailer, retailer_user)

    assert result["successful_rows"] == 2
    taxed = Product.objects.get(name="Taxed Excel Product")
    untaxed = Product.objects.get(name="Untaxed Excel Product")
    assert taxed.hsn_code == "21069099"
    assert taxed.gst_rate == Decimal("18")
    assert untaxed.hsn_code == ""
    assert untaxed.gst_rate == Decimal("0")


@pytest.mark.django_db
def test_excel_rejects_unsupported_nonblank_gst_rate(retailer, retailer_user):
    csv_file = SimpleUploadedFile(
        "products.csv",
        b"name,price,quantity,gst_rate\nBad Tax Product,100,2,12\n",
        content_type="text/csv",
    )

    result = process_excel_upload(csv_file, retailer, retailer_user)

    assert result["successful_rows"] == 0
    assert result["failed_rows"] == 1
    assert "Unsupported GST rate" in result["error_log"][0]["error"]
    assert not Product.objects.filter(name="Bad Tax Product").exists()
