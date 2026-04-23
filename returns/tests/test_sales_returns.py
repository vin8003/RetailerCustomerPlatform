import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductBatch, ProductInventoryLog
from orders.models import Order, OrderItem
from returns.models import SalesReturn, SalesReturnItem
from retailers.models import RetailerCustomerMapping
from customers.models import CustomerLoyalty, LoyaltyTransaction

@pytest.mark.django_db
class TestSalesReturns:
    """
    Comprehensive tests for Sales Returns:
    - Stock update
    - Loyalty points reversal (proportional)
    - CRM metrics reversal
    """

    @pytest.fixture
    def setup_order(self, retailer, customer, product):
        # Create a delivered order with loyalty points
        order = Order.objects.create(
            retailer=retailer,
            customer=customer,
            subtotal=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
            status='delivered',
            payment_mode='cash',
            points_earned=Decimal("10.00") # 1% loyalty
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=10,
            unit_price=Decimal("100.00"),
            total_price=Decimal("1000.00")
        )
        # Setup Loyalty
        CustomerLoyalty.objects.create(customer=customer, retailer=retailer, points=Decimal("10.00"))
        # Setup CRM Mapping
        RetailerCustomerMapping.objects.create(
            retailer=retailer, 
            customer=customer, 
            total_spent=Decimal("1000.00"),
            total_orders=1
        )
        return order

    def test_sales_return_proportional_points_reversal(self, api_client, retailer_user, setup_order, product):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("sales-return-list")
        
        order = setup_order
        customer = order.customer
        order_item = order.items.first()
        
        # Return 5 units out of 10 (50% return)
        data = {
            "order_id": order.id,
            "refund_payment_mode": "cash",
            "items": [
                {
                    "product_id": product.id,
                    "order_item_id": order_item.id,
                    "quantity": 5,
                    "refund_unit_price": 100.00
                }
            ]
        }
        
        response = api_client.post(url, data, format='json')
        if response.status_code != status.HTTP_201_CREATED:
            print(f"DEBUG: Response data: {response.data}")
        assert response.status_code == status.HTTP_201_CREATED
        
        # 1. Verify Stock
        product.refresh_from_db()
        # Original was 50 (from fixture), Order took 10 (Wait, order creation doesn't auto-reduce in this test setup unless I call it)
        # Let's assume starting was 50. In setup_order I didn't reduce it.
        # But process_sales_return calls increase_quantity.
        # Initial 50 -> increase 5 = 55.
        assert product.quantity == 55 
        
        # 2. Verify Loyalty (Proportional)
        # Total subtotal 1000, points 10. Refund 500.
        # Revert = (500/1000) * 10 = 5 points.
        loyalty = CustomerLoyalty.objects.get(customer=customer, retailer=order.retailer)
        assert loyalty.points == Decimal("5.00")
        
        # 3. Verify CRM Mapping
        mapping = RetailerCustomerMapping.objects.get(customer=customer, retailer=order.retailer)
        assert mapping.total_spent == Decimal("500.00")
        
        # 4. Verify Transaction
        assert LoyaltyTransaction.objects.filter(customer=customer, transaction_type='redeem').exists()

    def test_sales_return_unauthenticated(self, api_client, setup_order):
        url = reverse("sales-return-list")
        response = api_client.post(url, {})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_search_order_for_return(self, api_client, retailer_user, setup_order):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("sales-return-search-order")
        
        # Search by order number
        response = api_client.get(url, {"query": setup_order.order_number})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["id"] == setup_order.id
