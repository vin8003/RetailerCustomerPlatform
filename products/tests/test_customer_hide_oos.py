"""KAN-63: customer-facing product APIs hide tracked out-of-stock items."""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from products.models import Product


def _ids(response):
    data = response.data
    if isinstance(data, dict) and "results" in data:
        return [row["id"] for row in data["results"]]
    if isinstance(data, list):
        return [row["id"] for row in data]
    return []


def _make_product(retailer, category, brand, **kwargs):
    defaults = dict(
        retailer=retailer,
        category=category,
        brand=brand,
        price=Decimal("80.00"),
        original_price=Decimal("100.00"),
        quantity=10,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
        discount_percentage=Decimal("20.00"),
    )
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


@pytest.mark.django_db
class TestCustomerHideOutOfStockKAN63:
    def test_public_catalog_hides_tracked_zero_stock(
        self, api_client, retailer, category, brand, product
    ):
        oos = _make_product(
            retailer, category, brand, name="OOS Sugar", quantity=0
        )
        res = api_client.get(
            reverse("get_retailer_products_public", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK
        ids = _ids(res)
        assert product.id in ids
        assert oos.id not in ids

    def test_public_catalog_keeps_untracked_zero_quantity(
        self, api_client, retailer, category, brand
    ):
        untracked = _make_product(
            retailer,
            category,
            brand,
            name="Service Fee",
            quantity=0,
            track_inventory=False,
        )
        res = api_client.get(
            reverse("get_retailer_products_public", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK
        assert untracked.id in _ids(res)

    def test_public_catalog_shows_product_again_after_restock(
        self, api_client, retailer, category, brand
    ):
        item = _make_product(
            retailer, category, brand, name="Restock Oil", quantity=0
        )
        url = reverse("get_retailer_products_public", args=[retailer.id])
        assert item.id not in _ids(api_client.get(url))
        item.quantity = Decimal("12")
        item.save(update_fields=["quantity"])
        assert item.id in _ids(api_client.get(url))

    def test_retailer_catalog_still_shows_oos(
        self, api_client, retailer_user, retailer, category, brand
    ):
        oos = _make_product(
            retailer, category, brand, name="Retailer OOS", quantity=0
        )
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"))
        assert res.status_code == status.HTTP_200_OK
        assert oos.id in _ids(res)

    @patch(
        "products.views.smart_product_search",
        side_effect=lambda qs, q: qs.filter(name__icontains=q),
    )
    def test_public_search_hides_oos(
        self, _mock_search, api_client, retailer, category, brand
    ):
        in_stock = _make_product(
            retailer, category, brand, name="Search Milk In", quantity=8
        )
        oos = _make_product(
            retailer, category, brand, name="Search Milk OOS", quantity=0
        )
        res = api_client.get(
            reverse("search_products_public", args=[retailer.id]),
            {"search": "Search Milk"},
        )
        assert res.status_code == status.HTTP_200_OK
        ids = _ids(res)
        assert in_stock.id in ids
        assert oos.id not in ids

    def test_featured_hides_oos(self, api_client, retailer, category, brand):
        featured_oos = _make_product(
            retailer,
            category,
            brand,
            name="Featured OOS",
            quantity=0,
            is_featured=True,
        )
        res = api_client.get(
            reverse("get_retailer_featured_products", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK
        assert featured_oos.id not in _ids(res)

    def test_seasonal_hides_oos(self, api_client, retailer, category, brand):
        seasonal_oos = _make_product(
            retailer,
            category,
            brand,
            name="Seasonal OOS",
            quantity=0,
            is_seasonal=True,
        )
        res = api_client.get(
            reverse("get_seasonal_picks", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK
        assert seasonal_oos.id not in _ids(res)

    def test_deals_hides_oos(self, api_client, retailer, category, brand):
        deal_oos = _make_product(
            retailer,
            category,
            brand,
            name="Deal OOS",
            quantity=0,
            discount_percentage=Decimal("25.00"),
        )
        res = api_client.get(
            reverse("get_deals_of_the_day", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK
        assert deal_oos.id not in _ids(res)

    def test_new_arrivals_hides_oos(
        self, api_client, retailer, category, brand
    ):
        oos = _make_product(
            retailer, category, brand, name="New OOS", quantity=0
        )
        res = api_client.get(reverse("get_new_arrivals", args=[retailer.id]))
        assert res.status_code == status.HTTP_200_OK
        assert oos.id not in _ids(res)

    def test_related_group_variants_hide_oos(
        self, api_client, retailer, category, brand
    ):
        parent = _make_product(
            retailer,
            category,
            brand,
            name="Pack 1kg",
            quantity=20,
            product_group="Atta Pack",
        )
        sibling_oos = _make_product(
            retailer,
            category,
            brand,
            name="Pack 5kg OOS",
            quantity=0,
            product_group="Atta Pack",
        )
        sibling_ok = _make_product(
            retailer,
            category,
            brand,
            name="Pack 2kg",
            quantity=4,
            product_group="Atta Pack",
        )
        res = api_client.get(
            reverse(
                "get_product_detail_public",
                args=[retailer.id, parent.id],
            )
        )
        assert res.status_code == status.HTTP_200_OK
        variant_ids = [v["id"] for v in res.data.get("group_variants") or []]
        assert sibling_ok.id in variant_ids
        assert sibling_oos.id not in variant_ids
