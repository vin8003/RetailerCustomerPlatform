"""
Order notification dispatcher (OE-183 / F-0005).

Single entry point: event name → template → channel. Persists delivery rows
with retry metadata and last-error for staff visibility.
"""
import logging
from django.utils import timezone

from common.notification_catalog import (
    ALL_CHANNELS,
    CHANNEL_IN_APP,
    CHANNEL_PUSH,
    CHANNEL_SMS,
    MAX_DELIVERY_RETRIES,
    NOTIFICATION_DEFINITIONS,
    is_statutory_notification_type,
    notification_type_for_order_status,
    render_template,
)

logger = logging.getLogger(__name__)


def ensure_org_notification_config(organization):
    """Ensure OrgNotificationConfig exists for an org (idempotent)."""
    from retailers.models import OrgNotificationConfig

    if organization is None:
        return None
    row, _created = OrgNotificationConfig.objects.select_related(
        'organization',
    ).get_or_create(
        organization=organization,
    )
    return row


def get_disabled_types(organization, config=None):
    config = config or ensure_org_notification_config(organization)
    raw = config.disabled_types or []
    return set(raw) if isinstance(raw, list) else set()


def resolve_channel(organization, notification_type, config=None):
    """Pick channel from org config override or catalog default."""
    config = config or ensure_org_notification_config(organization)
    overrides = config.channel_overrides or {}
    if isinstance(overrides, dict) and notification_type in overrides:
        channel = overrides[notification_type]
        if channel in ALL_CHANNELS:
            return channel
    spec = NOTIFICATION_DEFINITIONS[notification_type]
    default = config.default_channel or spec['default_channel']
    return default if default in ALL_CHANNELS else spec['default_channel']


def is_notification_type_enabled(organization, notification_type, config=None):
    if is_statutory_notification_type(notification_type):
        return True
    return notification_type not in get_disabled_types(organization, config=config)


def _build_template_context(*, order=None, extra=None):
    ctx = dict(extra or {})
    if order is not None:
        ctx.setdefault('order_number', order.order_number)
        ctx.setdefault('order_id', order.id)
        ctx.setdefault('status', order.status)
    return ctx


def _send_in_app(*, recipient_user, title, message, data=None):
    from customers.models import CustomerNotification

    if recipient_user is None:
        return False, 'No recipient user for in_app channel'
    CustomerNotification.objects.create(
        customer=recipient_user,
        notification_type='order_update',
        title=title,
        message=message,
    )
    return True, None


def _send_push(*, recipient_user, title, message, data=None):
    from common.notifications import send_push_notification

    if recipient_user is None:
        return False, 'No recipient user for push channel'
    # Preserve customer inbox records for order status updates.
    if (data or {}).get('type') == 'order_status_update':
        in_ok, in_err = _send_in_app(
            recipient_user=recipient_user,
            title=title,
            message=message,
            data=data,
        )
        if not in_ok:
            return False, in_err
    ok = send_push_notification(
        user=recipient_user,
        title=title,
        message=message,
        data=data or {},
    )
    if not ok:
        return False, 'Failed to start push notification thread'
    return True, None


def _send_sms(*, recipient_user, message, data=None):
    from authentication.utils import send_sms_otp

    phone = getattr(recipient_user, 'phone_number', None) or ''
    phone = str(phone).strip()
    if not phone:
        return False, 'Recipient has no phone number for SMS channel'
    # Reuse SMS transport with a deterministic dummy payload for order updates.
    ok = send_sms_otp(phone, message[:160])
    if not ok:
        return False, 'Failed to start SMS send'
    return True, None


def _deliver_via_channel(*, channel, recipient_user, title, message, data=None):
    if channel == CHANNEL_IN_APP:
        return _send_in_app(
            recipient_user=recipient_user,
            title=title,
            message=message,
            data=data,
        )
    if channel == CHANNEL_PUSH:
        return _send_push(
            recipient_user=recipient_user,
            title=title,
            message=message,
            data=data,
        )
    if channel == CHANNEL_SMS:
        return _send_sms(
            recipient_user=recipient_user,
            message=message,
            data=data,
        )
    return False, f'Unsupported channel: {channel}'


def _attempt_delivery(delivery):
    """Try sending once; update delivery row in place."""
    payload = delivery.payload or {}
    title = payload.get('title', '')
    message = payload.get('message', '')
    data = payload.get('data') or {}

    success, error = _deliver_via_channel(
        channel=delivery.channel,
        recipient_user=delivery.recipient_user,
        title=title,
        message=message,
        data=data,
    )
    delivery.retry_count = (delivery.retry_count or 0) + 1
    if success:
        delivery.status = delivery.STATUS_SENT
        delivery.last_error = ''
        delivery.sent_at = timezone.now()
    else:
        delivery.status = delivery.STATUS_FAILED
        delivery.last_error = error or 'Unknown delivery error'
    delivery.save(
        update_fields=['status', 'retry_count', 'last_error', 'sent_at', 'updated_at']
    )
    return success


def dispatch_notification(
    *,
    organization,
    notification_type,
    recipient_user,
    context=None,
    order=None,
    location=None,
    channel=None,
    config=None,
    skip_module_check=False,
):
    """
    Dispatch one notification. Returns (delivery, skipped_reason).

    skipped_reason is set when the notification was intentionally not sent
    (disabled type, missing definition, etc.).
    """
    from retailers.models import OrgNotificationDelivery
    from retailers.module_flags import is_module_enabled

    if organization is None:
        return None, 'organization_required'
    if notification_type not in NOTIFICATION_DEFINITIONS:
        return None, 'unknown_notification_type'
    config = config or ensure_org_notification_config(organization)
    if not skip_module_check and not is_module_enabled(organization, 'notifications'):
        return None, 'module_disabled'
    if not is_notification_type_enabled(
        organization, notification_type, config=config
    ):
        return None, 'notification_type_disabled'

    spec = NOTIFICATION_DEFINITIONS[notification_type]
    ctx = _build_template_context(order=order, extra=context)
    title = render_template(spec['title_template'], ctx)
    message = render_template(spec['message_template'], ctx)
    resolved_channel = channel or resolve_channel(
        organization, notification_type, config=config
    )

    payload = {
        'title': title,
        'message': message,
        'data': {
            'type': 'order_status_update',
            'notification_type': notification_type,
            'event_name': spec['event_name'],
            **{k: str(v) for k, v in ctx.items()},
        },
    }

    delivery = OrgNotificationDelivery.objects.create(
        organization=organization,
        location=location,
        order=order,
        recipient_user=recipient_user,
        notification_type=notification_type,
        event_name=spec['event_name'],
        channel=resolved_channel,
        status=OrgNotificationDelivery.STATUS_PENDING,
        payload=payload,
    )
    _attempt_delivery(delivery)
    return delivery, None


def dispatch_order_status_notification(*, order, new_status, old_status=None):
    """
    Emit customer notification for an order status transition.

    Also sends silent retailer UI refresh (legacy behaviour preserved).
    """
    from common.notifications import send_silent_update

    notification_type = notification_type_for_order_status(new_status)
    if notification_type is None or order.customer is None:
        return None, 'no_notification_for_status'

    organization = order.retailer.organization
    if organization is None:
        from retailers.organization import ensure_organization_for_profile

        organization = ensure_organization_for_profile(order.retailer)

    delivery, skip = dispatch_notification(
        organization=organization,
        notification_type=notification_type,
        recipient_user=order.customer,
        order=order,
        location=order.retailer,
    )

    # Legacy silent refresh hooks (not part of dispatcher delivery log).
    send_silent_update(
        user=order.customer,
        event_type='order_refresh',
        data={'order_id': str(order.id)},
    )
    send_silent_update(
        user=order.retailer.user,
        event_type='order_refresh',
        data={'order_id': str(order.id)},
    )

    return delivery, skip


def retry_notification_delivery(delivery):
    """
    Retry a failed delivery when retries remain.

    Returns (delivery, error_message). error_message is None on success.
    """
    if delivery.status == delivery.STATUS_SENT:
        return delivery, None
    if delivery.retry_count >= MAX_DELIVERY_RETRIES:
        return delivery, 'Maximum retries exceeded'
    _attempt_delivery(delivery)
    if delivery.status == delivery.STATUS_SENT:
        return delivery, None
    return delivery, delivery.last_error or 'Retry failed'


def dispatch_bulk_notifications(
    *,
    organization,
    actor,
    notification_type,
    recipient_users,
    context=None,
    channel=None,
):
    """
    Staff-initiated bulk blast. Caller must enforce ``notifications.blast``.

    Returns list of (delivery, skip_reason) tuples.
    """
    config = ensure_org_notification_config(organization)
    results = []
    for user in recipient_users:
        delivery, skip = dispatch_notification(
            organization=organization,
            notification_type=notification_type,
            recipient_user=user,
            context=context,
            channel=channel,
            config=config,
            skip_module_check=True,
        )
        results.append((delivery, skip))
    return results
