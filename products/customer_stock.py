"""Customer-app stock visibility (KAN-63).

Tracked products with quantity <= 0 are hidden from customer listings.
Untracked products remain visible. Retailer-authenticated endpoints must not
enable the request flag.
"""
from functools import wraps
import threading

from django.db import models
from django.db.models import Q

CUSTOMER_IN_STOCK_Q = Q(track_inventory=False) | Q(quantity__gt=0)

_tls = threading.local()


class ProductManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(_tls, "hide_oos", False):
            return qs.filter(CUSTOMER_IN_STOCK_Q)
        return qs


def filter_in_stock_for_customer(queryset):
    """Exclude tracked out-of-stock rows from a product queryset."""
    return queryset.filter(CUSTOMER_IN_STOCK_Q)


def hide_oos_for_customer(view_func):
    """Wrap a customer-facing product view so listings omit tracked OOS rows."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        prev = getattr(_tls, "hide_oos", False)
        _tls.hide_oos = True
        try:
            return view_func(*args, **kwargs)
        finally:
            _tls.hide_oos = prev
    return wrapped
