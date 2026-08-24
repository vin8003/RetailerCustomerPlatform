"""Order list status query helpers (KAN-77)."""
from django.db.models import Exists, OuterRef, Q


STATUS_ALIASES = {
    'shipped': 'out_for_delivery',
}


def apply_order_status_filter(queryset, status_filter):
    """Filter an Order queryset by the retailer/customer status tab.

    ``returned`` matches orders whose status is ``returned`` *or* that have
    at least one sales return. POS returns historically left status as
    ``delivered``, so a strict status=returned filter missed them and the
    retailer Returned tab failed or looked empty.
    """
    if not status_filter or status_filter == 'all':
        return queryset

    status_filter = STATUS_ALIASES.get(status_filter, status_filter)

    if status_filter == 'returned':
        from returns.models import SalesReturn
        has_return = Exists(SalesReturn.objects.filter(order_id=OuterRef('pk')))
        return queryset.filter(Q(status='returned') | has_return)

    return queryset.filter(status=status_filter)
