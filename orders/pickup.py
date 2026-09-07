"""
Shop pickup helpers (OE-152 / F-0054).

Pickup fulfillment stays on unified Order (delivery_mode=pickup). Uses existing
ATP restore hooks and OE-183 notifications via Order.update_status — no
F-0113/F-0029 inventory engines or marketplace paths.
"""
from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from authentication.models import User
    from orders.models import Order

# Reuse OTP length convention from auth settings.
DEFAULT_PICKUP_CODE_LENGTH = getattr(settings, 'OTP_LENGTH', 6)

# Statuses where a packed pickup order is awaiting customer collection.
UNCOLLECTED_PICKUP_STATUSES = frozenset({'packed'})


def generate_pickup_code(*, length: int | None = None) -> str:
    """Generate a numeric pickup verification code (same length as OTP)."""
    code_length = length or DEFAULT_PICKUP_CODE_LENGTH
    upper = 10**code_length
    lower = 10 ** (code_length - 1)
    return str(secrets.randbelow(upper - lower) + lower)


def verify_pickup_collection(
    order: Order,
    pickup_code: str | None,
    *,
    customer_id: int | None = None,
) -> None:
    """
    Validate pickup collection verification before mark_delivered.

    Raises ValueError with a user-facing message when verification fails.
    """
    if order.delivery_mode != 'pickup':
        return

    if not pickup_code or not str(pickup_code).strip():
        raise ValueError('pickup_code is required to complete shop pickup collection')

    stored = order.pickup_code or ''
    if not stored or not secrets.compare_digest(str(stored), str(pickup_code).strip()):
        raise ValueError('Invalid pickup verification code')

    if customer_id is not None and order.customer_id is not None:
        if int(customer_id) != int(order.customer_id):
            raise ValueError('Customer identity does not match this pickup order')


def expire_uncollected_pickup_orders(*, now=None, retailer_id=None, actor=None):
    """
    Release ATP and cancel pickup orders uncollected past retailer policy hours.

    Returns a list of dicts describing each expired order (for tests/ops).
    Intended to be invoked by a management command or scheduled job.
    """
    from orders.inventory import restore_order_inventory
    from orders.models import Order

    now = now or timezone.now()
    qs = Order.objects.filter(
        delivery_mode='pickup',
        status__in=UNCOLLECTED_PICKUP_STATUSES,
        pickup_ready_at__isnull=False,
    ).select_related('retailer', 'customer')

    if retailer_id is not None:
        qs = qs.filter(retailer_id=retailer_id)

    expired = []
    for order in qs.iterator():
        policy_hours = getattr(order.retailer, 'pickup_uncollected_hours', None) or 48
        deadline = order.pickup_ready_at + timezone.timedelta(hours=policy_hours)
        if now < deadline:
            continue

        previous_status = order.status
        reason = (
            f'Uncollected shop pickup expired after {policy_hours} hours '
            f'(order #{order.order_number})'
        )
        order.update_status('cancelled', actor)
        order.cancellation_reason = reason
        order.cancelled_by = 'system'
        order.save(update_fields=['cancellation_reason', 'cancelled_by'])
        restore_order_inventory(order, actor, reason=reason)

        expired.append(
            {
                'order_id': order.id,
                'order_number': order.order_number,
                'previous_status': previous_status,
                'policy_hours': policy_hours,
                'pickup_ready_at': order.pickup_ready_at,
            }
        )

    return expired
