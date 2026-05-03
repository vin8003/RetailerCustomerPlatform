import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from customers.models import CustomerLoyalty, LoyaltyTransaction
from retailers.models import RetailerRewardConfig

logger = logging.getLogger(__name__)


def _get_loyalty_for_update(customer, retailer):
    loyalty = CustomerLoyalty.objects.select_for_update().filter(customer=customer, retailer=retailer).first()
    if loyalty:
        return loyalty
    return CustomerLoyalty.objects.create(customer=customer, retailer=retailer, points=0)


def redeem_points(order, amount):
    if amount <= 0 or not order.customer:
        return
    with transaction.atomic():
        loyalty = _get_loyalty_for_update(order.customer, order.retailer)
        loyalty.points -= amount
        loyalty.save(update_fields=['points', 'updated_at'])
        LoyaltyTransaction.objects.create(customer=order.customer, retailer=order.retailer, amount=amount, transaction_type='redeem', description=f"Redeemed on order #{order.order_number}")


def refund_redeemed_points(order):
    if order.points_redeemed <= 0 or not order.customer:
        return
    with transaction.atomic():
        loyalty = _get_loyalty_for_update(order.customer, order.retailer)
        loyalty.points += order.points_redeemed
        loyalty.save(update_fields=['points', 'updated_at'])
        LoyaltyTransaction.objects.create(customer=order.customer, retailer=order.retailer, amount=order.points_redeemed, transaction_type='refund', description=f"Refund from cancelled order #{order.order_number}")


def revert_earned_points(order):
    if order.points_earned <= 0 or not order.customer:
        return
    with transaction.atomic():
        loyalty = _get_loyalty_for_update(order.customer, order.retailer)
        loyalty.points = max(Decimal('0'), loyalty.points - order.points_earned)
        loyalty.save(update_fields=['points', 'updated_at'])
        LoyaltyTransaction.objects.create(customer=order.customer, retailer=order.retailer, amount=order.points_earned, transaction_type='redeem', description=f"Reverted earned points (Order #{order.order_number} cancelled after delivery)")
        order.points_earned = 0
        order.save(update_fields=['points_earned'])


def award_loyalty_points(order):
    if not order.customer:
        return False
    try:
        expiry_date = timezone.now() + timedelta(days=90)
        total_to_award = order.points_earned
        config = RetailerRewardConfig.objects.filter(retailer=order.retailer).first()
        if not (config and config.is_active):
            return False
        if order.subtotal >= config.loyalty_min_order_value:
            if config.earning_type == 'percentage':
                total_to_award += (order.subtotal * config.loyalty_earning_value) / Decimal('100.00')
            elif config.earning_type == 'points_per_amount' and config.loyalty_earning_value > 0:
                total_to_award += Decimal(str(order.subtotal // config.loyalty_earning_value))
        if total_to_award > 0:
            with transaction.atomic():
                loyalty = _get_loyalty_for_update(order.customer, order.retailer)
                loyalty.points += total_to_award
                loyalty.save(update_fields=['points', 'updated_at'])
                order.points_earned = total_to_award
                order.save(update_fields=['points_earned'])
                LoyaltyTransaction.objects.create(customer=order.customer, retailer=order.retailer, amount=total_to_award, transaction_type='earn', description=f"Earned from order #{order.order_number}", expiry_date=expiry_date)
        return True
    except Exception as e:
        logger.error(f"Error awarding points: {e}")
        return False
