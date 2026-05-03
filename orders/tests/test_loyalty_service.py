import pytest
from decimal import Decimal

from customers.models import CustomerLoyalty, LoyaltyTransaction
from orders.services.loyalty_service import refund_redeemed_points, revert_earned_points


@pytest.mark.django_db
def test_refund_redeemed_points(order, retailer):
    order.points_redeemed = Decimal('50.00')
    order.save(update_fields=['points_redeemed'])
    refund_redeemed_points(order)
    loyalty = CustomerLoyalty.objects.get(customer=order.customer, retailer=retailer)
    assert loyalty.points == Decimal('50.00')
    assert LoyaltyTransaction.objects.filter(transaction_type='refund').exists()


@pytest.mark.django_db
def test_revert_earned_points(order, retailer):
    CustomerLoyalty.objects.create(customer=order.customer, retailer=retailer, points=Decimal('30.00'))
    order.points_earned = Decimal('10.00')
    order.save(update_fields=['points_earned'])
    revert_earned_points(order)
    order.refresh_from_db()
    assert order.points_earned == 0
