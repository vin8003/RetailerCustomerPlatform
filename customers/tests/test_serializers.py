import pytest
from decimal import Decimal
from customers.serializers import (
    CustomerAddressSerializer, CustomerAddressUpdateSerializer,
    CustomerDashboardSerializer, CustomerProfileSerializer
)
from orders.models import Order


@pytest.mark.django_db
class TestCustomerAddressSerializer:
    def test_create_address(self, customer):
        data = {
            "title": "New Home",
            "address_line1": "101 Lane",
            "city": "Town",
            "state": "State",
            "pincode": "111222",
            "is_default": True
        }
        serializer = CustomerAddressSerializer(data=data, context={"customer": customer})
        assert serializer.is_valid()
        address = serializer.save()
        assert address.customer == customer
        assert address.is_default is True

    def test_invalid_pincode(self, customer):
        data = {"pincode": "12345", "title": "X", "address_line1": "Y", "city": "Z", "state": "S"}
        serializer = CustomerAddressSerializer(data=data, context={"customer": customer})
        assert not serializer.is_valid()
        assert "pincode" in serializer.errors


@pytest.mark.django_db
class TestCustomerDashboardSerializer:
    def test_dashboard_data(self, customer, retailer, address):
        # Create some orders for dashboard stats
        Order.objects.create(
            customer=customer,
            retailer=retailer,
            total_amount=Decimal("500.00"),
            subtotal=Decimal("500.00"),
            delivery_mode="delivery",
            payment_mode="upi",
            status="delivered",
            delivery_address=address,
            payment_status="verified"
        )
        Order.objects.create(
            customer=customer,
            retailer=retailer,
            total_amount=Decimal("300.00"),
            subtotal=Decimal("300.00"),
            delivery_mode="delivery",
            payment_mode="cash",
            status="pending",
            delivery_address=address
        )
        
        # Dashboard data is usually a dict passed to serializer
        dashboard_data = {
            "total_orders": 2,
            "pending_orders": 1,
            "delivered_orders": 1,
            "cancelled_orders": 0,
            "total_spent": 500.00,
            "wishlist_count": 0,
            "addresses_count": 1,
            "unread_notifications": 0,
            "recent_orders": [],
            "favorite_retailers": []
        }
        
        serializer = CustomerDashboardSerializer(dashboard_data)
        assert serializer.data["total_orders"] == 2
        assert float(serializer.data["total_spent"]) == 500.00
