"""
Retailer order inbox (OE-135 / F-0050).

Inbox is a query over the unified Order model (OE-131 / F-0049) — not a
separate engine. Staff list incoming orders for their org and take actions
allowed by the status state machine.

Scope: existing app/POS order sources only. F-0117 marketplace ingest,
MarketplaceOrder, and channel adapters are out of scope for this stack.
"""
from django.utils import timezone

from orders.domain.status_policy import ALLOWED_STATUS_TRANSITIONS, ensure_transition_allowed
from orders.access import order_list_queryset

# OE-131 unified Order sources in scope for the retailer inbox (not F-0117).
INBOX_ORDER_SOURCES = frozenset({'app', 'pos'})

# Active pipeline orders visible in the retailer inbox by default.
DEFAULT_INBOX_STATUSES = frozenset(
    {
        'pending',
        'waiting_for_customer_approval',
        'confirmed',
        'processing',
        'packed',
        'out_for_delivery',
    }
)

# Statuses that typically need immediate retailer action.
NEEDS_ACTION_STATUSES = frozenset({'pending', 'waiting_for_customer_approval'})

# Semantic inbox actions mapped to target order statuses.
INBOX_ACTION_TO_STATUS = {
    'accept': 'confirmed',
    'confirm': 'confirmed',
    'reject': 'cancelled',
    'cancel': 'cancelled',
    'start_processing': 'processing',
    'mark_packed': 'packed',
    'dispatch': 'out_for_delivery',
    'mark_delivered': 'delivered',
}

INBOX_ACTION_CHOICES = tuple((key, key) for key in INBOX_ACTION_TO_STATUS)


def target_status_for_inbox_action(action: str) -> str | None:
    """Return the order status an inbox action resolves to, or None if unknown."""
    return INBOX_ACTION_TO_STATUS.get(action)


def allowed_inbox_actions_for_status(current_status: str) -> list[str]:
    """Return inbox action names permitted from the given order status."""
    allowed_targets = set(ALLOWED_STATUS_TRANSITIONS.get(current_status, []))
    return sorted(
        action
        for action, target in INBOX_ACTION_TO_STATUS.items()
        if target in allowed_targets
    )


def validate_inbox_action(current_status: str, action: str) -> str:
    """
    Validate an inbox action against the status policy.

    Returns the target status or raises ValueError with a user-facing message.
    """
    target = target_status_for_inbox_action(action)
    if target is None:
        raise ValueError(f"Unknown inbox action '{action}'")
    try:
        ensure_transition_allowed(current_status, target)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return target


def build_inbox_queryset(location_ids):
    """
    Base queryset for retailer inbox list — org-scoped via location ids.

    Reuses OE-131 order_list_queryset (select_related, prefetch, annotations).
    """
    return (
        order_list_queryset()
        .filter(
            retailer_id__in=location_ids,
            source__in=INBOX_ORDER_SOURCES,
        )
        .order_by('-created_at')
    )


def apply_inbox_filters(queryset, query_params):
    """Apply inbox list filters from query parameters."""
    needs_action = query_params.get('needs_action')
    if needs_action is not None and str(needs_action).lower() in ('1', 'true', 'yes'):
        queryset = queryset.filter(status__in=NEEDS_ACTION_STATUSES)
    else:
        status_filter = query_params.get('status')
        if status_filter:
            if status_filter == 'shipped':
                status_filter = 'out_for_delivery'
            queryset = queryset.filter(status=status_filter)
        else:
            queryset = queryset.filter(status__in=DEFAULT_INBOX_STATUSES)

    source = query_params.get('source')
    if source:
        if source not in INBOX_ORDER_SOURCES:
            allowed = ', '.join(sorted(INBOX_ORDER_SOURCES))
            raise ValueError(
                f"Unknown source filter '{source}'; allowed values: {allowed}"
            )
        queryset = queryset.filter(source=source)

    location_id = query_params.get('location_id')
    if location_id:
        try:
            queryset = queryset.filter(retailer_id=int(location_id))
        except (TypeError, ValueError):
            # Ignore non-numeric location_id rather than 400 — staff may paste bad IDs.
            pass

    search = query_params.get('search')
    if search:
        queryset = queryset.filter(order_number__icontains=search)

    start_date = query_params.get('start_date')
    if start_date:
        try:
            start = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
            queryset = queryset.filter(created_at__date__gte=start)
        except ValueError:
            # Ignore unparseable start_date — treat as no date bound.
            pass

    end_date = query_params.get('end_date')
    if end_date:
        try:
            end = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
            queryset = queryset.filter(created_at__date__lte=end)
        except ValueError:
            # Ignore unparseable end_date — treat as no date bound.
            pass

    return queryset
