from django.db import transaction
from django.utils import timezone

from orders.models import OrderStatusLog
from .loyalty_service import award_loyalty_points, refund_redeemed_points, revert_earned_points
from .notification_service import notify_order_status_update


def update_order_status(order, new_status, user=None):
    old_status = order.status
    with transaction.atomic():
        order.status = new_status
        if new_status == 'confirmed':
            order.confirmed_at = timezone.now()
        elif new_status == 'delivered':
            order.delivered_at = timezone.now()
            if old_status != 'delivered':
                award_loyalty_points(order)
        elif new_status == 'cancelled':
            order.cancelled_at = timezone.now()
            if old_status != 'cancelled':
                refund_redeemed_points(order)
            if old_status == 'delivered':
                revert_earned_points(order)
        order.save()
        OrderStatusLog.objects.create(order=order, old_status=old_status, new_status=new_status, changed_by=user)
    notify_order_status_update(order, new_status, user)
    return True
