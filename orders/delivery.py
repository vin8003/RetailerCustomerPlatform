"""
Embedded shop courier assign (OE-275 / F-0119).

Delivery fulfillment stays on unified Order (delivery_mode=delivery). Staff assign
name/phone (+ optional ETA) when dispatching to out_for_delivery; persists
OrderDelivery and reuses OE-183 via Order.update_status — no rider User, fleet,
GPS, POD, or separate delivery app.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orders.models import Order


_INDIAN_MOBILE = re.compile(r'^(?:\+?91)?[6-9]\d{9}$')


def normalize_courier_phone(raw) -> str | None:
    """Return a 10-digit Indian mobile number, or None when it is not valid."""
    digits = re.sub(r'[\s\-()]', '', str(raw or ''))
    if not _INDIAN_MOBILE.match(digits):
        return None
    return digits[-10:]


def validate_courier_assign(*, delivery_mode: str, new_status: str, name, phone) -> None:
    """
    Require courier name/phone when dispatching a delivery order.

    Raises ValueError with a user-facing message when validation fails.
    """
    if new_status != 'out_for_delivery' or delivery_mode != 'delivery':
        return

    if not (name and str(name).strip()):
        raise ValueError('delivery_person_name is required when dispatching a delivery order')
    if not (phone and str(phone).strip()):
        raise ValueError('delivery_person_phone is required when dispatching a delivery order')
    if normalize_courier_phone(phone) is None:
        raise ValueError('delivery_person_phone must be a valid 10-digit mobile number')


def upsert_order_delivery(
    order: Order,
    *,
    delivery_person_name: str,
    delivery_person_phone: str,
    estimated_delivery_time=None,
):
    """Create or update OrderDelivery for an embedded courier assign."""
    from orders.models import OrderDelivery

    defaults = {
        'delivery_person_name': str(delivery_person_name).strip(),
        'delivery_person_phone': normalize_courier_phone(delivery_person_phone)
        or str(delivery_person_phone).strip(),
        'delivery_status': 'assigned',
    }
    if estimated_delivery_time is not None:
        defaults['estimated_delivery_time'] = estimated_delivery_time

    delivery, _created = OrderDelivery.objects.update_or_create(
        order=order,
        defaults=defaults,
    )
    return delivery


def mark_order_delivery_failed(order: Order) -> int:
    """
    Set OrderDelivery.delivery_status='failed' when a delivery row exists.

    Shop close-out only (OE-281). No-op when the order has no delivery row.
    """
    from orders.models import OrderDelivery

    return OrderDelivery.objects.filter(order=order).update(delivery_status='failed')
