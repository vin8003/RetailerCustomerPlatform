"""
OE-127 / F-0028 — hand-set on-hand quantity gate.

Sale/purchase still dual-write Product.quantity + ProductInventoryLog.
This module only rejects a *changed* product/batch on-hand on update / bulk
unless the caller has ``inventory.adjust``. Echoing the current number
(typical product-screen PUT/PATCH) does not require the perm.
"""
import json
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.response import Response

from retailers.organization import (
    ensure_org_rbac_bootstrap,
    get_organization_for_user,
    user_has_org_permission,
)

PERM_INVENTORY_ADJUST = 'inventory.adjust'


def _parse_batches(data):
    if not isinstance(data, dict):
        return None
    batches = data.get('batches')
    if isinstance(batches, str):
        try:
            batches = json.loads(batches)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(batches, list):
        return None
    return batches


def _qty_differs(raw, current):
    """True when submitted on-hand is not the stored value."""
    try:
        submitted = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return True
    if current is None:
        return True
    return submitted != Decimal(str(current))


def payload_sets_on_hand_quantity(data):
    """True when the body includes product or batch on-hand fields."""
    if not isinstance(data, dict):
        return False
    if 'quantity' in data:
        return True
    batches = _parse_batches(data)
    if batches is None:
        return False
    return any(
        isinstance(batch, dict) and 'quantity' in batch
        for batch in batches
    )


def submitted_on_hand_differs(product, data):
    """True when submitted product/batch qty would change stored on-hand."""
    if not isinstance(data, dict) or product is None:
        return False
    if 'quantity' in data and _qty_differs(data['quantity'], product.quantity):
        return True
    batches = _parse_batches(data)
    if not batches:
        return False
    batch_ids = [
        batch.get('id')
        for batch in batches
        if isinstance(batch, dict) and 'quantity' in batch and batch.get('id')
    ]
    existing = {}
    if batch_ids:
        existing = {
            row.id: row.quantity
            for row in product.batches.filter(id__in=batch_ids)
        }
    for batch in batches:
        if not isinstance(batch, dict) or 'quantity' not in batch:
            continue
        batch_id = batch.get('id')
        if not batch_id:
            return True
        current = existing.get(batch_id)
        if current is None or _qty_differs(batch['quantity'], current):
            return True
    return False


def bulk_items_set_on_hand_quantity(items):
    if not isinstance(items, list):
        return False
    return any(payload_sets_on_hand_quantity(item) for item in items)


def bulk_items_would_change_on_hand(items, products_by_id):
    """True when any bulk item would change that product's stored quantity."""
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict) or 'quantity' not in item:
            continue
        product = products_by_id.get(item.get('id'))
        if product is None or _qty_differs(item['quantity'], product.quantity):
            return True
    return False


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
    On deny, refresh system Admin role from the catalog (v7+) then re-check
    so stale ``OrgRole(admin).permissions`` do not block admin staff.
    """
    org = organization
    if org is None:
        org = get_organization_for_user(user)
    if org is None:
        return Response(
            {'error': 'Organization not found or access denied'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if user_has_org_permission(user, org, PERM_INVENTORY_ADJUST):
        return None
    ensure_org_rbac_bootstrap(org)
    if user_has_org_permission(user, org, PERM_INVENTORY_ADJUST):
        return None
    return inventory_adjust_denied_response()
