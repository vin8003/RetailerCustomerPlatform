import pytest
from unittest.mock import MagicMock
from common.permissions import (
    IsRetailerUser, IsCustomerUser, IsRetailerOwner, IsCustomerOwner,
    IsOwnerOrReadOnly, IsActiveRetailer, CanManageOrders
)

class MockUser:
    def __init__(self, user_type, is_authenticated=True, is_phone_verified=True):
        self.user_type = user_type
        self.is_authenticated = is_authenticated
        self.is_phone_verified = is_phone_verified

@pytest.fixture
def mock_request():
    request = MagicMock()
    return request

class TestCommonPermissions:
    
    def test_is_retailer_user(self, mock_request):
        permission = IsRetailerUser()
        
        # Retailer
        mock_request.user = MockUser('retailer')
        assert permission.has_permission(mock_request, None) is True
        
        # Customer
        mock_request.user = MockUser('customer')
        assert permission.has_permission(mock_request, None) is False
        
        # Unauthenticated
        mock_request.user = MockUser('retailer', is_authenticated=False)
        assert permission.has_permission(mock_request, None) is False

    def test_is_customer_user(self, mock_request):
        permission = IsCustomerUser()
        mock_request.user = MockUser('customer')
        assert permission.has_permission(mock_request, None) is True
        mock_request.user = MockUser('retailer')
        assert permission.has_permission(mock_request, None) is False

    def test_is_retailer_owner(self, mock_request):
        permission = IsRetailerOwner()
        retailer_user = MockUser('retailer')
        mock_request.user = retailer_user
        
        # Object belongs to retailer
        obj = MagicMock()
        obj.retailer.user = retailer_user
        assert permission.has_object_permission(mock_request, None, obj) is True
        
        # Object belongs to different retailer
        other_user = MockUser('retailer')
        obj.retailer.user = other_user
        assert permission.has_object_permission(mock_request, None, obj) is False

    def test_is_customer_owner(self, mock_request):
        permission = IsCustomerOwner()
        customer_user = MockUser('customer')
        mock_request.user = customer_user
        
        obj = MagicMock()
        obj.customer = customer_user
        assert permission.has_object_permission(mock_request, None, obj) is True
        
        obj.customer = MockUser('customer')
        assert permission.has_object_permission(mock_request, None, obj) is False

    def test_is_owner_or_read_only(self, mock_request):
        permission = IsOwnerOrReadOnly()
        user = MockUser('customer')
        mock_request.user = user
        
        class Obj:
            def __init__(self, customer):
                self.customer = customer
        
        obj = Obj(user)
        
        # Safe method (GET)
        mock_request.method = 'GET'
        assert permission.has_object_permission(mock_request, None, obj) is True
        
        # Write method (POST) - is owner
        mock_request.method = 'POST'
        assert permission.has_object_permission(mock_request, None, obj) is True
        
        # Write method (POST) - not owner
        obj.customer = MockUser('customer')
        assert permission.has_object_permission(mock_request, None, obj) is False

    @pytest.mark.django_db
    def test_is_active_retailer(self, mock_request, retailer):
        permission = IsActiveRetailer()
        mock_request.user = retailer.user
        
        # Active
        retailer.is_active = True
        retailer.save()
        assert permission.has_permission(mock_request, None) is True
        
        # Inactive
        retailer.is_active = False
        retailer.save()
        assert permission.has_permission(mock_request, None) is False

    def test_can_manage_orders(self, mock_request):
        permission = CanManageOrders()
        user = MockUser('retailer')
        mock_request.user = user
        
        order = MagicMock()
        order.retailer.user = user
        
        # Retailer owner of order
        assert permission.has_object_permission(mock_request, None, order) is True
        
        # Customer owner of order
        user_cust = MockUser('customer')
        mock_request.user = user_cust
        order.customer = user_cust
        assert permission.has_object_permission(mock_request, None, order) is True
