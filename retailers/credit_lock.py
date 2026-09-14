"""
Khata credit limit + due-days lock (OE-143 / F-0052).

Evaluated on POS credit finalize. Override reuses ``orders.update``
(no new finance / credit-override catalog code). Payment paths are
not locked.
"""
from decimal import Decimal

from django.utils import timezone

from retailers.audit_log import record_org_audit_event
from retailers.models import OrgAuditLog
from retailers.organization import get_organization_for_user, user_has_org_permission

# Reuse existing catalog code (no finance / credit-override invent).
PERM_CREDIT_OVERRIDE = 'orders.update'
REASON_CREDIT_LIMIT = 'credit_limit'
REASON_CREDIT_OVERDUE = 'credit_overdue'


class CreditOverrideDenied(Exception):
    """Caller requested a credit override without ``orders.update``."""


def is_credit_override_requested(data):
    raw = None
    if hasattr(data, 'get'):
        raw = data.get('credit_override')
    if raw is True or raw == 1:
        return True
    if isinstance(raw, str) and raw.strip().lower() in {'1', 'true', 'yes'}:
        return True
    return False


def _as_decimal(value):
    if value is None:
        return Decimal('0.00')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _elapsed_due_days(outstanding_since, now):
    start = timezone.localtime(outstanding_since).date()
    end = timezone.localtime(now).date()
    return (end - start).days


def credit_sale_lock_reasons(mapping, credit_amount, *, now=None):
    """
    Return lock reason codes for a credit sale against running outstanding.

    ``credit_limit`` of 0 and ``credit_due_days`` of null are unset (no lock).
    Due-days uses ``outstanding_since`` on the mapping, not bill-wise aging.
    """
    amount = _as_decimal(credit_amount)
    if amount <= 0 or mapping is None:
        return []

    now = now or timezone.now()
    reasons = []

    limit = _as_decimal(mapping.credit_limit)
    if limit > 0:
        projected = _as_decimal(mapping.current_balance) + amount
        if projected > limit:
            reasons.append(REASON_CREDIT_LIMIT)

    due_days = mapping.credit_due_days
    balance = _as_decimal(mapping.current_balance)
    if (
        due_days is not None
        and balance > 0
        and mapping.outstanding_since is not None
        and _elapsed_due_days(mapping.outstanding_since, now) >= due_days
    ):
        reasons.append(REASON_CREDIT_OVERDUE)

    return reasons


def format_credit_lock_error(mapping, credit_amount, reasons):
    parts = []
    if REASON_CREDIT_LIMIT in reasons:
        available = _as_decimal(mapping.credit_limit) - _as_decimal(mapping.current_balance)
        parts.append(
            f"Credit limit exceeded. "
            f"Limit: ₹{mapping.credit_limit}, "
            f"Current balance: ₹{mapping.current_balance}, "
            f"Available: ₹{max(available, 0)}"
        )
    if REASON_CREDIT_OVERDUE in reasons:
        parts.append("Credit sales locked: outstanding is past due days.")
    return " ".join(parts) or "Credit sales locked."


def assert_credit_sale_allowed(mapping, credit_amount, data, *, user, retailer, now=None):
    """
    Raise ValueError (400) or CreditOverrideDenied (403) when locked.

    Returns a dict for a granted override, or None when no override is needed.
    """
    reasons = credit_sale_lock_reasons(mapping, credit_amount, now=now)
    if not reasons:
        return None
    if not is_credit_override_requested(data):
        raise ValueError(format_credit_lock_error(mapping, credit_amount, reasons))

    org = getattr(retailer, 'organization', None)
    if org is None:
        org = get_organization_for_user(user)
    if org is None or not user_has_org_permission(user, org, PERM_CREDIT_OVERRIDE):
        raise CreditOverrideDenied(
            'Insufficient permissions to override credit lock'
        )
    return {
        'organization': org,
        'reasons': reasons,
        'mapping': mapping,
        'credit_amount': _as_decimal(credit_amount),
    }


def record_credit_override_audit(*, pending, actor, retailer, order):
    if not pending:
        return None
    mapping = pending['mapping']
    return record_org_audit_event(
        organization=pending['organization'],
        actor=actor,
        action=OrgAuditLog.ACTION_GRANT,
        object_type=OrgAuditLog.OBJECT_CREDIT_OVERRIDE,
        object_id=order.id,
        location=retailer,
        summary_before={
            'mapping_id': mapping.id,
            'credit_limit': str(mapping.credit_limit),
            'current_balance': str(mapping.current_balance),
            'credit_due_days': mapping.credit_due_days,
            'reasons': list(pending['reasons']),
        },
        summary_after={
            'order_id': order.id,
            'credit_amount': str(pending['credit_amount']),
            'override': True,
        },
    )
