"""
Retailer CRM lookup helpers (OE-212 / F-0105).

Extends RetailerCustomerMapping + Order. No second CRM engine, no merge,
no rewards. Org-scoped reads only.
"""
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status
from rest_framework.response import Response

from authentication.utils import normalize_phone_number
from orders.models import Order
from retailers.models import RetailerCustomerMapping
from retailers.module_flags import require_module_enabled

# Catalog has no crm.* / customers.read. Closest code that authorizes
# reading order rows is orders.read (export / full history only).
PERM_HISTORY_EXPORT = 'orders.read'
RECENT_ORDERS_LIMIT = 20
MIN_PHONE_DIGITS = 10


def _retailer_only_response():
    return Response(
        {'error': 'Only retailers can access this endpoint'},
        status=status.HTTP_403_FORBIDDEN,
    )


def _permission_denied_response():
    return Response(
        {'error': 'Insufficient permissions to export customer history'},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_retailer_crm_access(user):
    """Retailer JWT + customers module. Staff resolve via org membership."""
    if not user or not getattr(user, 'is_authenticated', False):
        return None, _permission_denied_response()
    if getattr(user, 'user_type', None) != 'retailer':
        return None, _retailer_only_response()
    return require_module_enabled(user, 'customers')


def is_export_requested(query_params):
    raw = query_params.get('export', '')
    if raw is True:
        return True
    return str(raw).lower() in ('1', 'true', 'yes')


def require_history_export_permission(user, organization):
    """Full history uses closest catalog code: orders.read."""
    from retailers.organization import user_has_org_permission

    if user_has_org_permission(user, organization, PERM_HISTORY_EXPORT):
        return None
    return _permission_denied_response()


def parse_lookup_phone(raw):
    """
    Return last-10 digits or an error Response.

    Empty / short numbers are 400 — this is a lookup, not typeahead.
    """
    last_10 = normalize_phone_number((raw or '').strip())
    if not last_10 or len(last_10) < MIN_PHONE_DIGITS:
        return None, Response(
            {'error': 'phone is required (at least 10 digits)'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return last_10, None


def find_org_customer_mapping(organization, last_10):
    """Most recently updated mapping in this org whose customer phone matches."""
    if organization is None or not last_10:
        return None
    return (
        RetailerCustomerMapping.objects.filter(retailer__organization=organization)
        .filter(
            Q(customer__phone_number__endswith=last_10)
            | Q(customer__username__endswith=last_10)
        )
        .select_related('customer', 'customer__customer_profile', 'retailer')
        .order_by('-updated_at', '-id')
        .first()
    )


def org_customer_orders_qs(organization, customer=None, last_10=''):
    """
    POS + app orders for this phone inside the org.

    Includes customer-linked rows and leftover guest_mobile POS rows.
    """
    if organization is None:
        return Order.objects.none()

    parts = Q()
    if customer is not None:
        parts |= Q(customer=customer)
    if last_10:
        parts |= Q(customer__isnull=True, guest_mobile__endswith=last_10)
    if not parts:
        return Order.objects.none()

    return Order.objects.filter(retailer__organization=organization).filter(parts)


def annotated_history_qs(orders_qs):
    return (
        orders_qs.select_related('retailer')
        .annotate(items_count_annotated=Count('items'))
        .order_by('-created_at', '-id')
    )


def order_totals(orders_qs):
    return orders_qs.aggregate(
        total_orders=Count('id'),
        total_spent=Coalesce(
            Sum('total_amount', filter=Q(status='delivered')),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )


def serialize_order_row(order):
    return {
        'id': order.id,
        'order_number': order.order_number,
        'source': order.source or 'app',
        'status': order.status,
        'total_amount': order.total_amount,
        'created_at': order.created_at,
        'items_count': getattr(order, 'items_count_annotated', 0),
    }


def customer_summary(mapping, last_10, totals, guest_name=None):
    if mapping is None:
        return {
            'customer_id': None,
            'mapping_id': None,
            'customer_name': guest_name or '',
            'phone_number': last_10,
            'nickname': None,
            'registration_status': 'guest',
            'total_orders': totals.get('total_orders') or 0,
            'total_spent': totals.get('total_spent') or Decimal('0.00'),
            'current_balance': None,
            'credit_limit': None,
        }

    user = mapping.customer
    name = (mapping.nickname or user.get_full_name() or user.username or '').strip()
    phone = (
        normalize_phone_number(user.phone_number or '')
        or normalize_phone_number(user.username or '')
        or last_10
    )
    return {
        'customer_id': user.id,
        'mapping_id': mapping.id,
        'customer_name': name,
        'phone_number': phone,
        'nickname': mapping.nickname,
        'registration_status': user.registration_status or 'shadow',
        'total_orders': totals.get('total_orders') or 0,
        'total_spent': totals.get('total_spent') or Decimal('0.00'),
        'current_balance': mapping.current_balance,
        'credit_limit': mapping.credit_limit,
    }
