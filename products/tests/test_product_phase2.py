import pytest
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductCategory, ProductBrand, SearchTelemetry, ProductInventoryLog
from decimal import Decimal
from unittest.mock import patch

@pytest.mark.django_db
class TestProductPhase2:

    @patch('products.views.smart_product_search')
    def test_search_products_with_facets(self, mock_smart_search, api_client, retailer, product, category, brand):
        # Trigger search_products view (Lines 359-430)
        mock_smart_search.side_effect = lambda qs, q: qs.filter(name__icontains=q)
        
        api_client.force_authenticate(user=retailer.user)
        # Correct URL name from urls.py: name='search_products'
        url = reverse('search_products')
        
        # Test with search and facets
        response = api_client.get(url, {'search': 'Rice', 'category': category.id})
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data
        assert 'facets' in response.data
        assert len(response.data['facets']['categories']) >= 1
        
        # Verify SearchTelemetry
        assert SearchTelemetry.objects.filter(query='Rice', retailer=retailer).exists()

    def test_create_product_flow(self, api_client, retailer, category, brand):
        # Trigger create_product view (Lines 432-494)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('create_product')
        data = {
            'name': 'New Bulk Product',
            'description': 'Description',
            'category': category.id,
            'brand': brand.id,
            'price': 150.00,
            'original_price': 200.00,
            'quantity': 100,
            'unit': 'kg',
            'track_inventory': True
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['name'] == 'New Bulk Product'
        
        # Verify Inventory Log
        assert ProductInventoryLog.objects.filter(
            product__name='New Bulk Product', 
            log_type='added',
            reason='Initial product creation'
        ).exists()

    def test_update_product_inventory_tracking(self, api_client, retailer, product):
        # Trigger update_product view (Lines 548-622)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('update_product', kwargs={'product_id': product.id})
        
        # Increase quantity by 50
        new_qty = product.quantity + 50
        response = api_client.patch(url, {'quantity': new_qty})
        assert response.status_code == status.HTTP_200_OK
        
        product.refresh_from_db()
        assert product.quantity == new_qty
        
        # Verify Inventory Log
        log = ProductInventoryLog.objects.filter(product=product).latest('created_at')
        assert log.log_type == 'added'
        assert log.quantity_change == 50

    def test_delete_product_soft(self, api_client, retailer, product):
        # Trigger delete_product view (Lines 624-653)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('delete_product', kwargs={'product_id': product.id})
        
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_200_OK
        
        product.refresh_from_db()
        assert product.is_active is False

    def test_get_retailer_products_filtering(self, api_client, retailer, product):
        # Trigger get_retailer_products filtering (Lines 241-357)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_products')
        
        # Test category filter branch
        response = api_client.get(url, {'category': product.category.id})
        assert response.status_code == status.HTTP_200_OK
        
        # Test low_stock filter branch
        response = api_client.get(url, {'low_stock': 'true'})
        assert response.status_code == status.HTTP_200_OK

    def test_get_product_stats_view(self, api_client, retailer, product):
        # Trigger get_product_stats
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_product_stats')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert 'total_products' in response.data

    def test_upload_products_csv_success(self, api_client, retailer):
        # Trigger upload_products_excel view (Lines 2183-2421)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('upload_products_excel')
        
        import csv
        from io import StringIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        f = StringIO()
        writer = csv.writer(f)
        writer.writerow(['name', 'price', 'quantity', 'category', 'brand'])
        writer.writerow(['CSV Product', '100', '10', 'Groceries', 'TestBrand'])
        
        csv_file = SimpleUploadedFile("test.csv", f.getvalue().encode('utf-8'), content_type="text/csv")
        
        response = api_client.post(url, {'file': csv_file}, format='multipart')
        assert response.status_code == status.HTTP_200_OK
        assert 'successful_rows' in response.data

    @patch('products.views.SearchVector')
    def test_smart_product_search_logic_branches(self, mock_vector, api_client, retailer, product):
        # Trigger smart_product_search lines 147-232
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_products_public', kwargs={'retailer_id': retailer.id})
        
        # Test with search query to trigger branch
        response = api_client.get(url, {'q': 'Rice'}) # 'Test Rice 5kg'
        assert response.status_code == status.HTTP_200_OK

    def test_get_retailer_products_filters(self, api_client, retailer, product):
        # Trigger get_retailer_products extensive filters (Lines 269-311)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_products')
        
        # Comprehensive filter list
        filters = [
            {'is_active': 'true'},
            {'is_featured': 'true'},
            {'is_seasonal': 'true'},
            {'is_available': 'true'},
            {'in_stock': 'true'},
            {'brand': 'Test'}
        ]
        
        for f in filters:
            response = api_client.get(url, f)
            assert response.status_code == status.HTTP_200_OK

    def test_product_discovery_lanes(self, api_client, retailer, product):
        # Trigger Featured, Best Selling, seasonal picks (Lines 35-45 in URLs)
        api_client.force_authenticate(user=retailer.user)
        
        # 1. Featured
        url_feat = reverse('get_retailer_featured_products', kwargs={'retailer_id': retailer.id})
        response = api_client.get(url_feat)
        assert response.status_code == status.HTTP_200_OK
        
        # 2. Best Selling
        url_best = reverse('get_best_selling_products', kwargs={'retailer_id': retailer.id})
        response = api_client.get(url_best)
        assert response.status_code == status.HTTP_200_OK
        
        # 3. Seasonal Picks
        url_seasonal = reverse('get_seasonal_picks', kwargs={'retailer_id': retailer.id})
        response = api_client.get(url_seasonal)
        assert response.status_code == status.HTTP_200_OK

    def test_category_and_brand_management(self, api_client, retailer):
        # Trigger create_product_category and create_product_brand (Lines 52, 59 in URLs)
        api_client.force_authenticate(user=retailer.user)
        
        url_brand = reverse('create_product_brand')
        response = api_client.post(url_brand, {'name': 'New Tech Brand'})
        assert response.status_code == status.HTTP_201_CREATED
        brand_id = response.data['id']
        
        from products.models import ProductCategory
        cat = ProductCategory.objects.create(name='Test Category Update')
        
        # 3. Update Category
        url_cat_up = reverse('update_product_category', kwargs={'category_id': cat.id})
        response = api_client.patch(url_cat_up, {'description': 'New Desc'})
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT, status.HTTP_404_NOT_FOUND]
        
        cat_id_to_delete = response.data['id'] if response.status_code == status.HTTP_200_OK else cat.id

        # 4. Delete Category
        url_cat_del = reverse('delete_product_category', kwargs={'category_id': cat_id_to_delete})
        response = api_client.delete(url_cat_del)
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT, status.HTTP_404_NOT_FOUND]

    def test_demand_insights_and_master_search(self, api_client, retailer):
        # Trigger get_demand_insights and search_master_product (Lines 15, 16 in URLs)
        api_client.force_authenticate(user=retailer.user)
        
        # 1. Demand Insights
        url_di = reverse('get_demand_insights')
        response = api_client.get(url_di)
        assert response.status_code == status.HTTP_200_OK
        
        # 2. Master Product Search
        url_ms = reverse('search_master_product')
        response = api_client.get(url_ms, {'barcode': '123456'})
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]

    def test_product_metadata_completion(self, api_client, retailer):
        # Trigger get_all_categories and get_product_groups (Lines 51, 56)
        api_client.force_authenticate(user=retailer.user)
        
        # 1. All Categories
        url_all = reverse('get_all_categories')
        response = api_client.get(url_all)
        assert response.status_code == status.HTTP_200_OK
        
        # 2. Product Groups
        url_group = reverse('get_product_groups')
        response = api_client.get(url_group)
        assert response.status_code == status.HTTP_200_OK

    def test_additional_discovery_lanes(self, api_client, retailer):
        # Trigger remaining discovery lanes (Lines 41-45 in URLs)
        api_client.force_authenticate(user=retailer.user)
        
        lanes = ['get_deals_of_the_day', 'get_budget_buys', 'get_trending_products', 'get_new_arrivals']
        for lane in lanes:
            url = reverse(lane, kwargs={'retailer_id': retailer.id})
            response = api_client.get(url)
            assert response.status_code == status.HTTP_200_OK

    def test_recommended_products(self, api_client, retailer):
        # Trigger get_recommended_products (Line 48)
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_recommended_products', kwargs={'retailer_id': retailer.id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
