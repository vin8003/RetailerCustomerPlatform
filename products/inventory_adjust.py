"""
OE-127 / F-0028 — hand-set on-hand quantity gate.

Sale/purchase still dual-write Product.quantity + ProductInventoryLog.
This module only rejects free-form quantity (and batch qty) on product
update / bulk unless the caller has ``inventory.adjust``.
"""
import json

from rest_framework import status
from rest_framework.response import Response

from retailers.organization import get_organization_for_user, user_has_org_permission

PERM_INVENTORY_ADJUST = 'inventory.adjust'


def payload_sets_on_hand_quantity(data):
    """True when the request tries to hand-set product or batch on-hand."""
    if not isinstance(data, dict):
        return False
    if 'quantity' in data:
        return True
    batches = data.get('batches')
    if isinstance(batches, str):
        try:
            batches = json.loads(batches)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
    if not isinstance(batches, list):
        return False
    return any(
        isinstance(batch, dict) and 'quantity' in batch
        for batch in batches
    )


def bulk_items_set_on_hand_quantity(items):
    if not isinstance(items, list):
        return False
    return any(payload_sets_on_hand_quantity(item) for item in items)


def inventory_adjust_denied_response():
    return Response(
        {'error': 'Inventory adjust permission required'},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_inventory_adjust(user, organization=None):
    """
    Return a 403/404 Response when the user may not hand-set on-hand.

    ``organization`` may be passed to avoid a second profile lookup on
    the owner happy path. Owner is implicit admin (full catalog).
    """
    org = organization
    if org is None:
        org = get_organization_for_user(user)
    if org is None:
        return Response(
            {'error': 'Retailer profile not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if not user_has_org_permission(user, org, PERM_INVENTORY_ADJUST):
        return inventory_adjust_denied_response()
    return None
