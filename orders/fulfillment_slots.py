"""
Pickup and delivery fulfillment windows (OE-243 / F-0115).

30-minute slots derived from existing RetailerOperatingHours — no parallel hours
model. Capacity is retailer-configurable per slot. Express is out of scope for v1.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, time
from typing import Iterable

import pytz
from django.db import transaction
from django.utils import timezone

from orders.models import Order
from retailers.models import RetailerOperatingHours, RetailerProfile

SLOT_MINUTES = 30
DEFAULT_TIMEZONE = 'Asia/Kolkata'
MAX_SLOT_LIST_DAYS = 14

ACTIVE_SLOT_STATUSES = frozenset(
    {
        'pending',
        'waiting_for_customer_approval',
        'confirmed',
        'processing',
        'packed',
        'out_for_delivery',
    }
)

DAYS_OF_WEEK = [
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday',
]


class FulfillmentSlotError(ValueError):
    """User-facing slot validation failure."""


def retailer_timezone(retailer: RetailerProfile):
    tz_name = getattr(retailer, 'timezone', None) or DEFAULT_TIMEZONE
    try:
        return pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone(DEFAULT_TIMEZONE)


def _time_add_minutes(value: time, minutes: int) -> time:
    combined = datetime.combine(date.today(), value) + timedelta(minutes=minutes)
    return combined.time()


def align_slot_start(dt: datetime) -> datetime:
    """Round down to the nearest 30-minute boundary."""
    if dt.minute < 30:
        return dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(minute=30, second=0, microsecond=0)


def slot_end(slot_start: datetime) -> datetime:
    return slot_start + timedelta(minutes=SLOT_MINUTES)


def normalize_slot_start(retailer: RetailerProfile, slot_start) -> datetime:
    """Accept aware datetime; align and validate 30-minute grid in retailer TZ."""
    tz = retailer_timezone(retailer)
    if timezone.is_naive(slot_start):
        slot_start = tz.localize(slot_start)
    else:
        slot_start = slot_start.astimezone(tz)
    aligned = align_slot_start(slot_start)
    if aligned != slot_start:
        raise FulfillmentSlotError('Fulfillment slot must align to 30-minute boundaries')
    return aligned


def operating_hours_map(retailer: RetailerProfile) -> dict[str, RetailerOperatingHours]:
    rows = RetailerOperatingHours.objects.filter(retailer=retailer)
    return {row.day_of_week: row for row in rows}


def generate_day_slot_starts(
    day: date,
    hours_row: RetailerOperatingHours | None,
    tz,
) -> list[datetime]:
    if (
        hours_row is None
        or not hours_row.is_open
        or not hours_row.opening_time
        or not hours_row.closing_time
    ):
        return []

    slots: list[datetime] = []
    cursor = hours_row.opening_time
    while True:
        end = _time_add_minutes(cursor, SLOT_MINUTES)
        if end > hours_row.closing_time:
            break
        slots.append(tz.localize(datetime.combine(day, cursor)))
        cursor = end
    return slots


def iter_slot_starts(
    retailer: RetailerProfile,
    *,
    days: int = 7,
    hours_by_day: dict[str, RetailerOperatingHours] | None = None,
    now=None,
) -> list[datetime]:
    """Return future slot starts within operating hours for the next ``days`` calendar days."""
    if days < 1 or days > MAX_SLOT_LIST_DAYS:
        raise FulfillmentSlotError(f'days must be between 1 and {MAX_SLOT_LIST_DAYS}')

    tz = retailer_timezone(retailer)
    hours_by_day = hours_by_day if hours_by_day is not None else operating_hours_map(retailer)
    now = now or timezone.now()
    local_now = now.astimezone(tz)
    today = local_now.date()

    starts: list[datetime] = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        day_name = DAYS_OF_WEEK[day.weekday()]
        for slot_start in generate_day_slot_starts(day, hours_by_day.get(day_name), tz):
            if slot_start >= align_slot_start(local_now):
                starts.append(slot_start)
    return starts


def is_slot_within_operating_hours(
    retailer: RetailerProfile,
    slot_start: datetime,
    *,
    hours_by_day: dict[str, RetailerOperatingHours] | None = None,
) -> bool:
    tz = retailer_timezone(retailer)
    local_start = slot_start.astimezone(tz)
    day_name = DAYS_OF_WEEK[local_start.weekday()]
    hours_by_day = hours_by_day if hours_by_day is not None else operating_hours_map(retailer)
    hours_row = hours_by_day.get(day_name)
    if (
        hours_row is None
        or not hours_row.is_open
        or not hours_row.opening_time
        or not hours_row.closing_time
    ):
        return False

    local_end = local_start + timedelta(minutes=SLOT_MINUTES)
    opening_dt = tz.localize(datetime.combine(local_start.date(), hours_row.opening_time))
    closing_dt = tz.localize(datetime.combine(local_start.date(), hours_row.closing_time))
    return local_start >= opening_dt and local_end <= closing_dt


def slot_capacity(retailer: RetailerProfile) -> int:
    return max(1, int(getattr(retailer, 'fulfillment_slot_capacity', 5) or 5))


def booked_counts_for_slots(
    retailer: RetailerProfile,
    slot_starts: Iterable[datetime],
    delivery_mode: str,
) -> dict[datetime, int]:
    """Single aggregate query — no per-slot SELECT loop."""
    unique_starts = list({s for s in slot_starts})
    if not unique_starts:
        return {}

    rows = (
        Order.objects.filter(
            retailer=retailer,
            delivery_mode=delivery_mode,
            fulfillment_slot_start__in=unique_starts,
            status__in=ACTIVE_SLOT_STATUSES,
        )
        .values('fulfillment_slot_start')
        .order_by()
    )
    from django.db.models import Count

    aggregated = rows.annotate(booked=Count('id'))
    return {row['fulfillment_slot_start']: row['booked'] for row in aggregated}


def build_slot_payloads(
    retailer: RetailerProfile,
    *,
    delivery_mode: str,
    days: int = 7,
    now=None,
) -> list[dict]:
    hours_by_day = operating_hours_map(retailer)
    starts = iter_slot_starts(retailer, days=days, hours_by_day=hours_by_day, now=now)
    booked = booked_counts_for_slots(retailer, starts, delivery_mode)
    capacity = slot_capacity(retailer)
    tz = retailer_timezone(retailer)

    payloads = []
    for slot_start in starts:
        booked_count = booked.get(slot_start, 0)
        remaining = max(0, capacity - booked_count)
        payloads.append(
            {
                'slot_start': slot_start.astimezone(pytz.UTC).isoformat(),
                'slot_end': slot_end(slot_start).astimezone(pytz.UTC).isoformat(),
                'slot_start_local': slot_start.isoformat(),
                'slot_end_local': slot_end(slot_start).isoformat(),
                'timezone': str(tz),
                'capacity': capacity,
                'booked': booked_count,
                'remaining': remaining,
                'is_available': remaining > 0,
            }
        )
    return payloads


def _booked_count_locked(
    retailer: RetailerProfile,
    slot_start: datetime,
    delivery_mode: str,
    *,
    exclude_order_id=None,
) -> int:
    qs = Order.objects.select_for_update().filter(
        retailer=retailer,
        fulfillment_slot_start=slot_start,
        delivery_mode=delivery_mode,
        status__in=ACTIVE_SLOT_STATUSES,
    )
    if exclude_order_id is not None:
        qs = qs.exclude(pk=exclude_order_id)
    return qs.count()


def validate_slot_bookable(
    retailer: RetailerProfile,
    slot_start: datetime,
    delivery_mode: str,
    *,
    exclude_order_id=None,
    hours_by_day: dict[str, RetailerOperatingHours] | None = None,
    now=None,
) -> datetime:
    """Return normalized slot_start or raise FulfillmentSlotError."""
    normalized = normalize_slot_start(retailer, slot_start)
    tz = retailer_timezone(retailer)
    now = now or timezone.now()
    if normalized < align_slot_start(now.astimezone(tz)):
        raise FulfillmentSlotError('Fulfillment slot is in the past')

    if delivery_mode == 'delivery' and not retailer.offers_delivery:
        raise FulfillmentSlotError('This retailer does not offer delivery')
    if delivery_mode == 'pickup' and not retailer.offers_pickup:
        raise FulfillmentSlotError('This retailer does not offer store pickup')

    if not is_slot_within_operating_hours(
        retailer, normalized, hours_by_day=hours_by_day
    ):
        raise FulfillmentSlotError('Fulfillment slot is outside operating hours')

    return normalized


def assert_slot_has_capacity(
    retailer: RetailerProfile,
    slot_start: datetime,
    delivery_mode: str,
    *,
    exclude_order_id=None,
) -> None:
    if _booked_count_locked(
        retailer, slot_start, delivery_mode, exclude_order_id=exclude_order_id
    ) >= slot_capacity(retailer):
        raise FulfillmentSlotError('Fulfillment slot is fully booked')


@transaction.atomic
def book_fulfillment_slot(
    order: Order,
    slot_start,
    *,
    delivery_mode: str | None = None,
    now=None,
) -> datetime:
    """Reserve a slot on ``order``; serializes via retailer row lock."""
    delivery_mode = delivery_mode or order.delivery_mode
    retailer = RetailerProfile.objects.select_for_update().get(pk=order.retailer_id)
    hours_by_day = operating_hours_map(retailer)
    normalized = validate_slot_bookable(
        retailer,
        slot_start,
        delivery_mode,
        exclude_order_id=order.pk,
        hours_by_day=hours_by_day,
        now=now,
    )
    assert_slot_has_capacity(
        retailer, normalized, delivery_mode, exclude_order_id=order.pk
    )
    order.fulfillment_slot_start = normalized
    order.save(update_fields=['fulfillment_slot_start', 'updated_at'])
    return normalized


@transaction.atomic
def reschedule_fulfillment_slot(
    order: Order,
    slot_start,
    *,
    by_staff: bool = False,
    now=None,
) -> datetime:
    """
    Move an order to a new slot.

    Shopper and staff share the same open/capacity rules (no hard cutoff in v1).
    """
    retailer = RetailerProfile.objects.select_for_update().get(pk=order.retailer_id)
    if order.status in {'delivered', 'cancelled', 'returned'}:
        raise FulfillmentSlotError('Cannot reschedule a completed or cancelled order')

    hours_by_day = operating_hours_map(retailer)
    normalized = validate_slot_bookable(
        retailer,
        slot_start,
        order.delivery_mode,
        exclude_order_id=order.pk,
        hours_by_day=hours_by_day,
        now=now,
    )
    assert_slot_has_capacity(
        retailer, normalized, order.delivery_mode, exclude_order_id=order.pk
    )
    order.fulfillment_slot_start = normalized
    order.save(update_fields=['fulfillment_slot_start', 'updated_at'])
    return normalized
