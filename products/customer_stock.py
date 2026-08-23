"""Customer-app stock visibility (KAN-63).

Tracked products with quantity <= 0 are hidden from customer listings.
Untracked products remain visible. Retailer-authenticated endpoints must not
use this filter.
"""
from django.db.models import Q

CUSTOMER_IN_STOCK_Q = Q(track_inventory=False) | Q(quantity__gt=0)


def filter_in_stock_for_customer(queryset):
    """Exclude tracked out-of-stock rows from a product queryset."""
    return queryset.filter(CUSTOMER_IN_STOCK_Q)
