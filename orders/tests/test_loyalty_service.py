import pytest
from decimal import Decimal

from authentication.models import User
from customers.models import CustomerLoyalty, CustomerReferral, LoyaltyTransaction
from orders.services.loyalty_service import award_loyalty_points, refund_redeemed_points, revert_earned_points
from retailers.models import RetailerRewardConfig


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


@pytest.mark.django_db
def test_award_loyalty_points_applies_referral_rewards(order, retailer):
    referrer = User.objects.create_user(username='referrer_user', email='ref@test.com', password='P', user_type='customer')
    config = RetailerRewardConfig.objects.create(
        retailer=retailer,
        is_active=True,
        is_referral_enabled=True,
        min_referral_order_amount=Decimal('100.00'),
        referral_reward_points=Decimal('20.00'),
        referee_reward_points=Decimal('10.00'),
    )
    CustomerReferral.objects.create(referrer=referrer, retailer=retailer, referee=order.customer, is_rewarded=False)

    assert award_loyalty_points(order) is True

    referral = CustomerReferral.objects.get(retailer=retailer, referee=order.customer)
    assert referral.is_rewarded is True
    referrer_loyalty = CustomerLoyalty.objects.get(customer=referrer, retailer=retailer)
    referee_loyalty = CustomerLoyalty.objects.get(customer=order.customer, retailer=retailer)
    assert referrer_loyalty.points == config.referral_reward_points
    assert referee_loyalty.points >= config.referee_reward_points
    assert LoyaltyTransaction.objects.filter(customer=referrer, description__contains='Referral reward').exists()
    assert LoyaltyTransaction.objects.filter(customer=order.customer, description__contains='referred by').exists()
