"""The retailer product search feeds the purchase bill, so a hit carries cost, stock and tax fields."""
from decimal import Decimal

import pytest
from django.urls import reverse

from products.models import Product


@pytest.fixture
def costed_product(product):
    Product.objects.filter(pk=product.pk).update(
        purchase_price=Decimal("72.50"), hsn_code="1006", gst_rate=Decimal("5.00"),
    )
    return product


@pytest.mark.django_db
def test_retailer_search_returns_purchase_bill_fields(api_client, retailer, costed_product):
    api_client.force_authenticate(user=retailer.user)
    res = api_client.get(reverse("search_products"))
    assert res.status_code == 200
    row = next(r for r in res.data["results"] if r["id"] == costed_product.id)
    assert Decimal(str(row["purchase_price"])) == Decimal("72.50")
    assert row["hsn_code"] == "1006"
    assert Decimal(str(row["gst_rate"])) == Decimal("5.00")
    assert row["barcode"] == costed_product.barcode
    assert "quantity" in row and "name" in row


@pytest.mark.django_db
def test_public_search_does_not_expose_cost(api_client, retailer, costed_product):
    res = api_client.get(reverse("search_products_public", args=[retailer.id]))
    assert res.status_code == 200
    row = next(r for r in res.data["results"] if r["id"] == costed_product.id)
    assert "purchase_price" not in row
