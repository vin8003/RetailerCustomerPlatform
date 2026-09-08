"""
Unified order access control (OE-131 / F-0049).

Org-scoped staff RBAC, module gate, and location resolution for POS + app
order APIs. Extends F-0002 permissions and F-0004 module flags without
forking the Order model.
"""
from decimal import Decimal

from django.db.models import Count, DecimalField, Exists, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status
from rest_framework.response import Response

from retailers.models import RetailerCustomerMapping, RetailerProfile
from retailers.module_flags import is_module_enabled, module_disabled_response
from retailers.organization import (
    get_organization_for_user,
    user_has_org_permission,
    is_org_owner,
    get_active_staff_membership,
)

PERM_ORDERS_READ = 'orders.read'
PERM_ORDERS_CREATE = 'orders.create'
PERM_ORDERS_UPDATE = 'orders.update'

ORDER_PERMISSION_CODES = frozenset(
    {PERM_ORDERS_READ, PERM_ORDERS_CREATE, PERM_ORDERS_UPDATE}
)


def _permission_denied_response():
    return Response(
        {'error': 'Insufficient permissions for order operations'},
        status=status.HTTP_403_FORBIDDEN,
    )


def _retailer_only_response():
    return Response(
        {'error': 'Only retailers can perform this order operation'},
        status=status.HTTP_403_FORBIDDEN,
    )


def _org_not_found_response():
    return Response(
        {'error': 'Retailer profile not found'},
        status=status.HTTP_404_NOT_FOUND,
    )


def retailer_locations_for_org(organization):
    """All shop locations (RetailerProfile rows) belonging to an org."""
    if organization is None:
        return RetailerProfile.objects.none()
    return RetailerProfile.objects.filter(organization=organization)


def order_list_queryset():
    """Bounded queryset for order list endpoints (tenant-safe filters applied in views)."""
    from returns.models import SalesReturn

    from .models import Order, OrderFeedback, RetailerRating

    nickname_subq = RetailerCustomerMapping.objects.filter(
        retailer_id=OuterRef('retailer_id'),
        customer_id=OuterRef('customer_id'),
    ).values('nickname')[:1]
    refund_subq = (
        SalesReturn.objects.filter(order_id=OuterRef('pk'))
        .values('order_id')
        .annotate(total=Sum('refund_amount'))
        .values('total')[:1]
    )
    has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
    has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))

    return (
        Order.objects.select_related(
            'retailer',
            'customer',
            'customer__customer_profile',
        )
        .prefetch_related(
            'payment_transactions',
            'returns',
            'feedback',
            'retailer_rating',
        )
        .annotate(
            items_count_annotated=Count('items', distinct=True),
            has_feedback_annotated=has_feedback_subquery,
            has_rating_annotated=has_rating_subquery,
            refund_total_annotated=Coalesce(
                Subquery(refund_subq),
                Value(Decimal('0')),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            customer_nickname_annotated=Subquery(nickname_subq),
        )
    )


def order_detail_queryset():
    """Bounded queryset for order detail and status mutation responses."""
    from django.db.models import Prefetch

    from .models import Order, OrderItem

    return Order.objects.select_related(
        'retailer',
        'customer',
        'customer__customer_profile',
        'delivery_address',
        'delivery_info',
    ).prefetch_related(
        Prefetch(
            'items',
            queryset=OrderItem.objects.select_related('product', 'batch').prefetch_related(
                'returns'
            ),
        ),
        'payment_transactions',
        'returns',
        'applied_offers',
        'applied_offers__offer',
        'chat_messages',
        'feedback',
        'retailer_rating',
    )


def require_retailer_orders_access(user, permission_code, *, check_module=True):
    """
    Validate retailer JWT, org membership, optional orders module, and RBAC.

    Returns (organization, locations_qs, None) when allowed, else
    (None, None, error Response).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None, None, _permission_denied_response()
    if user.user_type != 'retailer':
        return None, None, _retailer_only_response()

    org = get_organization_for_user(user)
    if org is None:
        return None, None, _org_not_found_response()

    if check_module and not is_module_enabled(org, 'orders'):
        return None, None, module_disabled_response('orders')

    if permission_code not in ORDER_PERMISSION_CODES:
        return None, None, _permission_denied_response()
    if not user_has_org_permission(user, org, permission_code):
        return None, None, _permission_denied_response()

    locations = retailer_locations_for_org(org)
    return org, locations, None


def get_order_for_retailer(user, order_id, permission_code):
    """Fetch an order scoped to the caller's org locations."""
    _org, locations, err = require_retailer_orders_access(user, permission_code)
    if err is not None:
        return None, err

    order = order_detail_queryset().filter(id=order_id, retailer__in=locations).first()
    if order is None:
        return None, Response(
            {'error': 'Order not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return order, None


def resolve_pos_retailer_location(user, location_id=None):
    """
    Resolve the RetailerProfile (location) for POS order creation.

    Staff without their own shop profile must pass ``location_id`` when the
    org has multiple locations.
    """
    _org, locations, err = require_retailer_orders_access(user, PERM_ORDERS_CREATE)
    if err is not None:
        return None, err

    if location_id is not None:
        retailer = locations.filter(id=location_id).first()
        if retailer is None:
            return None, Response(
                {'error': 'Invalid location for this organization'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return retailer, None

    own_location = locations.filter(user=user).first()
    if own_location is not None:
        return own_location, None

    location_count = locations.count()
    if location_count == 1:
        return locations.first(), None

    return None, Response(
        {
            'error': (
                'location_id is required when the organization has '
                'multiple shop locations'
            ),
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def check_retailer_accepts_customer_orders(retailer):
    """
    Module gate for customer-facing order placement against a retailer.

    Returns (True, None) or (False, error Response).
    """
    if retailer is None:
        return False, Response(
            {'error': 'Retailer not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    org = retailer.organization
    if org is None:
        from retailers.organization import ensure_organization_for_profile

        org = ensure_organization_for_profile(retailer)

    if not is_module_enabled(org, 'orders'):
        return False, module_disabled_response('orders')
    return True, None


def staff_served_location_ids(user, organization):
    """
    RetailerProfile ids the user may operate on within the org.

    Owner: all locations. Shop profile holder: linked location(s). Staff seat:
    ``served_location_ids`` on membership (single-location orgs fall back to
    the sole location when the list is empty).
    """
    if organization is None:
        return []

    if is_org_owner(user, organization):
        return list(
            retailer_locations_for_org(organization).values_list('id', flat=True)
        )

    profile_ids = list(
        RetailerProfile.objects.filter(
            organization=organization,
            user=user,
        ).values_list('id', flat=True)
    )
    if profile_ids:
        return profile_ids

    membership = get_active_staff_membership(user, organization)
    if membership is None:
        return []

    org_location_ids = set(
        retailer_locations_for_org(organization).values_list('id', flat=True)
    )
    served = membership.served_location_ids or []
    if served:
        return [location_id for location_id in served if location_id in org_location_ids]

    if len(org_location_ids) == 1:
        return list(org_location_ids)

    return []


def _location_not_served_response():
    return Response(
        {'error': 'Order location is not served by this staff member'},
        status=status.HTTP_403_FORBIDDEN,
    )


def retailer_served_location_ids(user, permission_code):
    """
    Return served location id list for inbox-style filters, or error Response.
    """
    org, _locations, err = require_retailer_orders_access(user, permission_code)
    if err is not None:
        return None, err
    return staff_served_location_ids(user, org), None


def get_order_for_retailer_served(user, order_id, permission_code):
    """Fetch an order scoped to org and staff-served locations."""
    order, err = get_order_for_retailer(user, order_id, permission_code)
    if err is not None:
        return None, err

    org = get_organization_for_user(user)
    served_ids = staff_served_location_ids(user, org)
    if order.retailer_id not in served_ids:
        return None, _location_not_served_response()
    return order, None


def retailer_location_ids(user, permission_code):
    """
    Return location id list for retailer list/detail filters, or error Response.
    """
    _org, locations, err = require_retailer_orders_access(user, permission_code)
    if err is not None:
        return None, err
    return list(locations.values_list('id', flat=True)), None
