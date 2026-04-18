import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from common.pagination import (
    StandardResultsSetPagination, SmallResultsSetPagination,
    CustomPagination, ProductPagination
)

@pytest.fixture
def api_request():
    factory = APIRequestFactory()
    request = factory.get('/')
    return Request(request)

class TestCommonPagination:
    
    def test_standard_pagination(self, api_request):
        paginator = StandardResultsSetPagination()
        data = ["item1", "item2"]
        
        # Using a proper mock structure
        page = MagicMock()
        page.paginator = MagicMock()
        page.paginator.count = 2
        page.paginator.num_pages = 1
        page.number = 1
        paginator.page = page
        paginator.request = api_request
        
        response = paginator.get_paginated_response(data)
        assert response.status_code == 200
        assert response.data['count'] == 2
        assert response.data['total_pages'] == 1
        assert response.data['results'] == data

    def test_custom_pagination(self, api_request):
        paginator = CustomPagination()
        data = ["item1"]
        
        page = MagicMock()
        page.paginator.count = 1
        page.paginator.num_pages = 1
        page.number = 1
        page.has_next.return_value = False
        page.has_previous.return_value = False
        page.start_index.return_value = 1
        page.end_index.return_value = 1
        paginator.page = page
        
        response = paginator.get_paginated_response(data)
        assert 'pagination' in response.data
        assert response.data['pagination']['count'] == 1
        assert response.data['results'] == data

from unittest.mock import MagicMock
