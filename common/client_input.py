"""
Ids, amounts and dates that clients send in query strings and request bodies.

A malformed value is the client's mistake, so these raise DRF ValidationError (400)
instead of letting ValueError / InvalidOperation surface as a 500. Upper bounds keep
values inside the order, return and batch columns they end up in; precision is left
to those columns, as before.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework import serializers

_MAX_ID = 2 ** 63 - 1  # BigAutoField
_MAX_QUANTITY = Decimal('1000000000')  # DecimalField(max_digits=12, decimal_places=3)
_MAX_MONEY = Decimal('100000000')  # DecimalField(max_digits=10, decimal_places=2)


def _invalid(name, message):
    return serializers.ValidationError({name: [message]})


def id_value(raw, name):
    """Positive whole-number id."""
    if isinstance(raw, bool):
        raise _invalid(name, 'Must be a whole number.')
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise _invalid(name, 'Must be a whole number.') from None
    if not 1 <= value <= _MAX_ID:
        raise _invalid(name, 'Must be a positive id.')
    return value


def decimal_value(raw, name):
    """Any finite number."""
    if isinstance(raw, bool) or raw is None:
        raise _invalid(name, 'Must be a number.')
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise _invalid(name, 'Must be a number.') from None
    if not value.is_finite():
        raise _invalid(name, 'Must be a number.')
    return value


def quantity_value(raw, name, allow_zero=False):
    """Sale or return quantity: above zero, or zero when allowed."""
    value = decimal_value(raw, name)
    if value < 0 or (value == 0 and not allow_zero):
        raise _invalid(name, 'Must be more than zero.' if not allow_zero else 'Cannot be negative.')
    if value >= _MAX_QUANTITY:
        raise _invalid(name, 'Is too large.')
    return value


def money_value(raw, name):
    """Amount in rupees: zero or more."""
    value = decimal_value(raw, name)
    if value < 0:
        raise _invalid(name, 'Cannot be negative.')
    if value >= _MAX_MONEY:
        raise _invalid(name, 'Is too large.')
    return value


def date_value(raw, name):
    """Calendar date in YYYY-MM-DD format."""
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        raise _invalid(name, 'Use a date in YYYY-MM-DD format.') from None


def list_of_objects(raw, name):
    """A JSON list whose entries are all objects (line items)."""
    if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
        raise _invalid(name, 'Must be a list of objects.')
    return raw


def error_message(exc):
    """'field: message' text for views that answer {'error': '...'}."""
    detail = exc.detail
    if isinstance(detail, dict):
        parts = []
        for field, messages in detail.items():
            messages = messages if isinstance(messages, list) else [messages]
            parts.append(f"{field}: {' '.join(str(m) for m in messages)}")
        return ' '.join(parts)
    if isinstance(detail, list):
        return ' '.join(str(m) for m in detail)
    return str(detail)
