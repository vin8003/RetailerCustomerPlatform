"""Customer-app stock visibility (KAN-63).

Tracked products with quantity <= 0 are hidden from customer listings.
Batch-tracked products are hidden when no unexpired batch has stock (OE-149),
since that stock cannot be sold. Pack children sell from their parent's stock,
so the same rule applies to the parent's batches. Untracked products remain
visible. Retailer-authenticated endpoints must not enable the request flag.
"""
from functools import wraps
import threading

from django.apps import apps
from django.db import models
from django.db.models import Exists, OuterRef, Q

def customer_in_stock_q():
    """KAN-63 visibility, with batch-tracked stock counted only while unexpired."""
    ProductBatch = apps.get_model('products', 'ProductBatch')
    saleable_batch = ProductBatch.objects.filter(
        ProductBatch.saleable_q(),
        product=OuterRef('pk'),
        is_active=True,
        quantity__gt=0,
    )
    parent_saleable_batch = ProductBatch.objects.filter(
        ProductBatch.saleable_q(),
        product=OuterRef('parent_bulk_product'),
        is_active=True,
        quantity__gt=0,
    )
    # Mirrors Product.saleable_quantity(): a child's stock is its parent's saleable stock.
    parent_can_sell = (
        Q(parent_bulk_product__isnull=True)
        | Q(parent_bulk_product__track_inventory=False)
        | Q(parent_bulk_product__has_batches=False)
        | Exists(parent_saleable_batch)
    )
    return Q(track_inventory=False) | (
        Q(quantity__gt=0)
        & (Q(has_batches=False) | Exists(saleable_batch))
        & parent_can_sell
    )

_tls = threading.local()


class ProductManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(_tls, "hide_oos", False):
            # Customer listings: in stock and not held by moderation.
            return qs.filter(customer_in_stock_q(), moderation_status='ok')
        return qs


def filter_in_stock_for_customer(queryset):
    """Exclude tracked out-of-stock rows and moderation holds from a product queryset."""
    return queryset.filter(customer_in_stock_q(), moderation_status='ok')


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
