"""
Unified order access control (OE-131 / F-0049).

Org-scoped staff RBAC, module gate, and location resolution for POS + app
order APIs. Extends F-0002 permissions and F-0004 module flags without
forking the Order model.
"""
from rest_framework import status
from rest_framework.response import Response

from retailers.models import RetailerProfile
from retailers.module_flags import is_module_enabled, module_disabled_response
from retailers.organization import get_organization_for_user, user_has_org_permission

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

    from .models import Order

    order = (
        Order.objects.filter(id=order_id, retailer__in=locations)
        .select_related('retailer', 'customer', 'delivery_address')
        .first()
    )
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


def retailer_location_ids(user, permission_code):
    """
    Return location id list for retailer list/detail filters, or error Response.
    """
    _org, locations, err = require_retailer_orders_access(user, permission_code)
    if err is not None:
        return None, err
    return list(locations.values_list('id', flat=True)), None
