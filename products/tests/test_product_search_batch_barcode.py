"""KAN-72: retailer product search matches batch and extra barcodes."""
from decimal import Decimal

import pytest

from products.models import Product, ProductBatch
from products.search import product_barcode_match_q


def _ids(qs):
    return list(qs.values_list("id", flat=True))


@pytest.mark.django_db
class TestProductSearchMultiBatchBarcodeKAN72:
    def test_matches_primary_barcode(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            category=category,
            brand=brand,
            name="Primary Barcode Oil",
            price=Decimal("40.00"),
            quantity=10,
            barcode="8901111111111",
        )
        other = Product.objects.create(
            retailer=retailer,
            category=category,
            brand=brand,
            name="Unrelated",
            price=Decimal("10.00"),
            quantity=5,
            barcode="8900000000000",
        )
        ids = _ids(
            Product.objects.filter(product_barcode_match_q("8901111111111")).distinct()
        )
        assert product.id in ids
        assert other.id not in ids

    def test_matches_additional_barcode(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            category=category,
            brand=brand,
            name="Extra Code Atta",
            price=Decimal("50.00"),
            quantity=10,
            barcode="8902222222222",
            additional_barcodes=["8903333333333"],
        )
        ids = _ids(
            Product.objects.filter(product_barcode_match_q("8903333333333")).distinct()
        )
        assert product.id in ids

    def test_matches_batch_barcode(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            category=category,
            brand=brand,
            name="Multi Batch Soap",
            price=Decimal("20.00"),
            quantity=10,
            barcode="8904444444444",
            has_batches=True,
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B1",
            barcode="8905555555555",
            price=Decimal("20.00"),
            quantity=4,
            is_active=True,
        )
        ids = _ids(
            Product.objects.filter(product_barcode_match_q("8905555555555")).distinct()
        )
        assert product.id in ids

    def test_matches_batch_additional_barcode(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            category=category,
            brand=brand,
            name="Batch Extra Tea",
            price=Decimal("30.00"),
            quantity=10,
            has_batches=True,
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="B2",
            barcode="8906666666666",
            additional_barcodes=["8907777777777"],
            price=Decimal("30.00"),
            quantity=3,
            is_active=True,
        )
        ids = _ids(
            Product.objects.filter(product_barcode_match_q("8907777777777")).distinct()
        )
        assert product.id in ids
