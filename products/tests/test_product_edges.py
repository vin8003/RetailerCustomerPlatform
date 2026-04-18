import pytest
from io import BytesIO
import pandas as pd
from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductCategory, ProductBrand, ProductUploadSession
from decimal import Decimal

@pytest.mark.django_db
class TestProductViewEdges:
    
    @patch('products.views.SearchVector')
    def test_apply_search_logic_fallback(self, mock_vector, api_client, retailer, product):
        # Trigger lines 210-226 in products/views.py (Search Fallback)
        # Mocking SearchVector to return something that results in 0 matches
        mock_vector.return_value = MagicMock()
        
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_products_public', kwargs={'retailer_id': retailer.id})
        # Use a query that exists in the name but we want to force the fallback
        response = api_client.get(url, {'q': 'Rice'}) # 'Test Rice 5kg' from conftest
        assert response.status_code == status.HTTP_200_OK
        # Check if results are there via fallback
        results = response.data['results'] if isinstance(response.data, dict) else response.data
        assert any('Rice' in p['name'] for p in results)

    def test_check_bulk_upload_valid_csv(self, api_client, retailer):
        # Trigger lines 1885-1950
        api_client.force_authenticate(user=retailer.user)
        
        # Create a CSV in memory
        df = pd.DataFrame([
            {'barcode': '123456', 'mrp': 100, 'rate': 90, 'stock qty': 50}
        ])
        csv_file = BytesIO()
        df.to_csv(csv_file, index=False)
        csv_file.seek(0)
        csv_file.name = 'test.csv'
        
        url = reverse('check_bulk_upload')
        response = api_client.post(url, {'file': csv_file}, format='multipart')
        if response.status_code != 200:
            print(f"DEBUG: Response data: {response.data}")
        assert response.status_code == status.HTTP_200_OK
        assert 'unmatched_count' in response.data

    def test_create_upload_session(self, api_client, retailer):
        # Trigger lines for CreateUploadSessionView
        api_client.force_authenticate(user=retailer.user)
        url = reverse('create_upload_session')
        response = api_client.post(url, {'name': 'Test Session'})
        assert response.status_code == status.HTTP_201_CREATED
        assert ProductUploadSession.objects.filter(retailer=retailer).exists()

    def test_get_deals_of_the_day(self, api_client, retailer, product):
        # Trigger lines for discovery lanes
        product.original_price = Decimal("100.00")
        product.price = Decimal("50.00") # 50% discount
        product.save()
        
        url = reverse('get_deals_of_the_day', kwargs={'retailer_id': retailer.id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        results = response.data['results'] if isinstance(response.data, dict) else response.data
        assert len(results) >= 1
