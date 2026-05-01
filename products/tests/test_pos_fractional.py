import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import Product, ProductBatch, ProductInventoryLog
from orders.models import Order, OrderItem

@pytest.mark.django_db
class TestPOSFractionalQuantity:
    def test_pos_billing_fractional_quantity(self, api_client, retailer_user, retailer, category, brand):
        api_client.force_authenticate(user=retailer_user)
        
        # Create a product with 10 units
        product = Product.objects.create(
            retailer=retailer, 
            name="Fractional Soap",
            category=category,
            brand=brand,
            price=Decimal('200.00'), 
            quantity=Decimal('10.000'),
            track_inventory=True,
            is_active=True,
            is_available=True
        )
        
        url = reverse('create_pos_order')
        data = {
            'items': [
                {
                    'product_id': product.id,
                    'quantity': 0.5,
                    'unit_price': 200.00
                }
            ],
            'payment_mode': 'cash',
            'subtotal': 100,
            'discount_amount': 0,
            'total_amount': 100
        }
        
        response = api_client.post(url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        # Check stock reduction
        product.refresh_from_db()
        assert product.quantity == Decimal('9.500')
        
        # Check order item quantity
        order = Order.objects.get(order_number=response.data['order']['order_number'])
        order_item = OrderItem.objects.get(order=order)
        assert order_item.quantity == Decimal('0.500')
        assert order_item.total_price == Decimal('100.00')
        
        # Check inventory log
        log = ProductInventoryLog.objects.filter(product=product).last()
        assert log.quantity_change == Decimal('-0.500')
        assert log.new_quantity == Decimal('9.500')
