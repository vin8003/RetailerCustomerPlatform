from customers.models import CustomerNotification
from common.notifications import send_push_notification, send_silent_update


STATUS_MESSAGES = {
    'confirmed': 'Your order has been confirmed',
    'processing': 'Your order is being processed',
    'packed': 'Your order has been packed',
    'out_for_delivery': 'Your order is out for delivery',
    'delivered': 'Your order has been delivered',
    'cancelled': 'Your order has been cancelled',
    'returned': 'Your order has been returned',
    'waiting_for_customer_approval': 'Order modifications require your approval',
}


def notify_order_status_update(order, new_status, user=None):
    if new_status not in STATUS_MESSAGES or not order.customer:
        return

    msg = STATUS_MESSAGES[new_status]
    CustomerNotification.objects.create(
        customer=order.customer,
        notification_type='order_update',
        title=f'Order #{order.order_number} Update',
        message=msg,
    )

    send_push_notification(
        user=order.customer,
        title=f"Order Update: #{order.order_number}",
        message=msg,
        data={'type': 'order_status_update', 'order_id': str(order.id), 'status': new_status},
    )
    send_silent_update(user=order.customer, event_type='order_refresh', data={'order_id': str(order.id)})
    send_silent_update(user=order.retailer.user, event_type='order_refresh', data={'order_id': str(order.id)})

    if user == order.customer:
        action_text = 'accepted' if new_status == 'confirmed' else 'rejected'
        send_push_notification(
            user=order.retailer.user,
            title=f"Order Update: #{order.order_number}",
            message=f"Customer has {action_text} the order modifications.",
            data={'type': 'order_status_update', 'order_id': str(order.id), 'status': new_status},
        )
