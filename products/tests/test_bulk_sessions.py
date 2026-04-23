import pytest
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductUploadSession, UploadSessionItem, ProductInventoryLog

@pytest.mark.django_db
class TestBulkUploadSessions:
    """
    Test Visual Bulk Upload flow (Session-based)
    """

    def test_full_bulk_upload_flow(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        
        # 1. Create Session
        url_create = reverse("create_upload_session")
        res_session = api_client.post(url_create, {"name": "Test Session"})
        assert res_session.status_code == status.HTTP_201_CREATED
        session_id = res_session.data["id"]
        
        # 2. Add Item
        url_add = reverse("add_session_item")
        data_item = {
            "session_id": session_id,
            "barcode": "SESSION-BAR-1",
            "name": "Session Product",
            "price": 250.00,
            "qty": 10
        }
        res_item = api_client.post(url_add, data_item)
        assert res_item.status_code == status.HTTP_201_CREATED
        
        # 3. Commit Session
        url_commit = reverse("commit_upload_session")
        res_commit = api_client.post(url_commit, {"session_id": session_id})
        assert res_commit.status_code == status.HTTP_200_OK
        assert res_commit.data["created_count"] == 1
        
        # 4. Verify Results
        assert Product.objects.filter(barcode="SESSION-BAR-1", retailer=retailer).exists()
        prod = Product.objects.get(barcode="SESSION-BAR-1")
        assert prod.quantity == 10
        
        # Verify Inventory Log
        assert ProductInventoryLog.objects.filter(product=prod, log_type='added').exists()
        
        # Session should be completed
        session = ProductUploadSession.objects.get(id=session_id)
        assert session.status == 'completed'

    def test_get_active_sessions(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        ProductUploadSession.objects.create(retailer=retailer, name="Active 1", status='active')
        ProductUploadSession.objects.create(retailer=retailer, name="Done 1", status='completed')
        
        url = reverse("get_active_sessions")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Active 1"
