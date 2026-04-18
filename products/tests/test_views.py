import pytest
from unittest.mock import patch
from django.urls import reverse
from rest_framework import status
from decimal import Decimal
from products.models import Product, ProductCategory, ProductBrand

def mock_smart_search(queryset, search_query):
    """Fallback mock search for SQLite tests"""
    if not search_query:
        return queryset
    return queryset.filter(name__icontains=search_query)


@pytest.mark.django_db
class TestGetRetailerProducts:

    def test_retailer_gets_products(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] >= 1

    def test_customer_forbidden(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_retailer_products"))
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_filter_by_category(self, api_client, retailer_user, retailer, product, category):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"), {"category": category.id})
        assert res.status_code == status.HTTP_200_OK

    def test_filter_by_category_name(self, api_client, retailer_user, retailer, product, category):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"), {"category": "Groceries"})
        assert res.status_code == status.HTTP_200_OK

    def test_filter_by_brand(self, api_client, retailer_user, retailer, product, brand):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"), {"brand": "TestBrand"})
        assert res.status_code == status.HTTP_200_OK

    def test_filter_by_active(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"), {"is_active": "true"})
        assert res.status_code == status.HTTP_200_OK

    def test_filter_in_stock(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"), {"in_stock": "true"})
        assert res.status_code == status.HTTP_200_OK

    def test_filter_low_stock(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"), {"low_stock": "true"})
        assert res.status_code == status.HTTP_200_OK

    @patch("products.views.smart_product_search", side_effect=mock_smart_search)
    def test_search_retailer_products(self, mock_search, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_products"), {"search": "Rice"})
        assert res.status_code == status.HTTP_200_OK
        assert mock_search.called


@pytest.mark.django_db
class TestCreateProduct:

    def test_create_product_success(self, api_client, retailer_user, retailer, category, brand):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(reverse("create_product"), {
            "name": "New Product",
            "category": category.id,
            "brand": brand.id,
            "price": "75.00",
            "quantity": 20,
            "unit": "piece",
        })
        assert res.status_code == status.HTTP_201_CREATED
        assert Product.objects.filter(name="New Product").exists()

    def test_create_product_customer_forbidden(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("create_product"), {"name": "X"})
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_create_product_missing_fields(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(reverse("create_product"), {})
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestGetProductDetail:

    def test_get_detail(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_product_detail", args=[product.id]))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["name"] == product.name

    def test_get_detail_customer_forbidden(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_product_detail", args=[product.id]))
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestUpdateProduct:

    def test_patch_product(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"price": "85.00"},
        )
        assert res.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.price == Decimal("85.00")

    def test_update_quantity_logs_inventory(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        api_client.patch(
            reverse("update_product", args=[product.id]),
            {"quantity": 100},
        )
        from products.models import ProductInventoryLog
        assert ProductInventoryLog.objects.filter(product=product).exists()

    def test_update_customer_forbidden(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        res = api_client.patch(
            reverse("update_product", args=[product.id]),
            {"price": "50"},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDeleteProduct:

    def test_soft_delete(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.delete(reverse("delete_product", args=[product.id]))
        assert res.status_code == status.HTTP_200_OK
        product.refresh_from_db()
        assert product.is_active is False

    def test_delete_customer_forbidden(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        res = api_client.delete(reverse("delete_product", args=[product.id]))
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestBulkUpdateProducts:

    def test_bulk_update(self, api_client, retailer_user, retailer, product, product2):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(
            reverse("bulk_update_products"),
            {
                "items": [
                    {"id": product.id, "price": "80.00", "quantity": 100},
                    {"id": product2.id, "is_active": "false"},
                ]
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["updated_count"] == 2
        product.refresh_from_db()
        assert product.price == Decimal("80.00")
        product2.refresh_from_db()
        assert product2.is_active is False

    def test_bulk_update_empty_items(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(
            reverse("bulk_update_products"),
            {"items": []},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_update_customer_forbidden(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.patch(
            reverse("bulk_update_products"),
            {"items": [{"id": 1}]},
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPublicProductEndpoints:

    def test_get_public_products(self, api_client, retailer, product):
        res = api_client.get(
            reverse("get_retailer_products_public", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK

    def test_get_public_products_filter_category(self, api_client, retailer, product, category):
        res = api_client.get(
            reverse("get_retailer_products_public", args=[retailer.id]),
            {"category": category.id},
        )
        assert res.status_code == status.HTTP_200_OK

    def test_get_public_products_filter_price(self, api_client, retailer, product):
        res = api_client.get(
            reverse("get_retailer_products_public", args=[retailer.id]),
            {"min_price": "50", "max_price": "200"},
        )
        assert res.status_code == status.HTTP_200_OK

    def test_get_public_products_ordering(self, api_client, retailer, product):
        for order in ["name", "-name", "price", "-price"]:
            res = api_client.get(
                reverse("get_retailer_products_public", args=[retailer.id]),
                {"ordering": order},
            )
            assert res.status_code == status.HTTP_200_OK

    def test_get_public_products_in_stock(self, api_client, retailer, product):
        res = api_client.get(
            reverse("get_retailer_products_public", args=[retailer.id]),
            {"in_stock": "true"},
        )
        assert res.status_code == status.HTTP_200_OK

    def test_get_public_product_detail(self, api_client, retailer, product):
        res = api_client.get(
            reverse("get_product_detail_public", args=[retailer.id, product.id])
        )
        assert res.status_code == status.HTTP_200_OK

    @patch("products.views.smart_product_search", side_effect=mock_smart_search)
    def test_public_search(self, mock_search, api_client, retailer, product):
        res = api_client.get(
            reverse("search_products_public", args=[retailer.id]),
            {"search": "Rice"},
        )
        assert res.status_code == status.HTTP_200_OK
        assert "results" in res.data
        assert mock_search.called

    def test_get_featured_products(self, api_client, retailer, product):
        res = api_client.get(
            reverse("get_retailer_featured_products", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK

    def test_get_retailer_categories(self, api_client, retailer, category, product):
        res = api_client.get(
            reverse("get_retailer_categories", args=[retailer.id])
        )
        assert res.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestProductStats:

    def test_get_stats_retailer(self, api_client, retailer_user, retailer, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_product_stats"))
        assert res.status_code == status.HTTP_200_OK

    def test_get_stats_customer_forbidden(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_product_stats"))
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCategoryManagement:

    def test_get_categories(self, api_client, retailer_user, retailer, category):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_product_categories"))
        assert res.status_code == status.HTTP_200_OK

    def test_create_category(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(reverse("create_product_category"), {"name": "Beverages"})
        assert res.status_code == status.HTTP_201_CREATED

    def test_create_category_customer_forbidden(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("create_product_category"), {"name": "X"})
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestBrandManagement:

    def test_get_brands(self, api_client, retailer_user, retailer, brand):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_product_brands"))
        assert res.status_code == status.HTTP_200_OK

    def test_create_brand(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(reverse("create_product_brand"), {"name": "NewBrand"})
        assert res.status_code == status.HTTP_201_CREATED
