"""
OE-127 / F-0028 — hand-set on-hand quantity gate.
OE-103 / F-0021 — same perm for parent-child pack link mutations.
OE-136 / F-0030 — same perm for ProductBatch.expiry_date mutations.

Sale/purchase still dual-write Product.quantity + ProductInventoryLog.
This module rejects a *changed* product/batch on-hand on update / bulk
unless the caller has ``inventory.adjust``. Echoing the current number
(typical product-screen PUT/PATCH) does not require the perm.

Pack-link fields (``conversion_factor``, ``parent_bulk_product``,
``is_parent_bulk``) on product create/update use the same perm when the
submitted value differs from stored (or is set on create). Bulk update
does not write those keys.

Batch ``expiry_date`` on product update uses the same perm when the
submitted date differs from stored (or a new batch is created with a
date). Echoing the current expiry (including null) does not require
the perm. Bulk update does not write expiry.
"""
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.response import Response

from retailers.organization import (
    ensure_org_rbac_bootstrap,
    get_organization_for_user,
    user_has_org_permission,
)

PERM_INVENTORY_ADJUST = 'inventory.adjust'

# Parent-child pack link fields on Product create/update (OE-103 / F-0021).
# Bulk update does not write these keys — see bulk_update_products.
PACK_LINK_FIELDS = ('conversion_factor', 'parent_bulk_product', 'is_parent_bulk')


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


def bulk_write_quantity(raw):
    """int() on-hand ``bulk_update_products`` would assign, or None if skipped."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


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
    """True when any bulk item would change stored qty the way bulk writes it."""
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict) or 'quantity' not in item:
            continue
        product = products_by_id.get(item.get('id'))
        if product is None:
            return True
        new_qty = bulk_write_quantity(item['quantity'])
        if new_qty is None:
            continue
        if product.quantity != new_qty:
            return True
    return False


def _as_bool(raw):
    if isinstance(raw, bool):
        return raw
    if raw in (1, '1', 'true', 'True', 'TRUE'):
        return True
    if raw in (0, '0', 'false', 'False', 'FALSE'):
        return False
    return bool(raw)


def _factor_differs(raw, current):
    if raw in (None, ''):
        return current is not None
    try:
        submitted = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return True
    if current is None:
        return True
    return submitted != Decimal(str(current))


def _parent_id_differs(raw, current_id):
    if raw in (None, ''):
        return current_id is not None
    try:
        submitted = int(raw)
    except (TypeError, ValueError):
        return True
    return submitted != current_id


def payload_sets_pack_link(data):
    """True when the body includes parent-child pack link fields."""
    if not isinstance(data, dict):
        return False
    return any(field in data for field in PACK_LINK_FIELDS)


def submitted_pack_link_differs(product, data):
    """True when submitted pack-link fields would change stored values."""
    if not isinstance(data, dict) or product is None:
        return False
    if 'conversion_factor' in data and _factor_differs(
        data['conversion_factor'], product.conversion_factor
    ):
        return True
    if 'is_parent_bulk' in data and _as_bool(data['is_parent_bulk']) != bool(
        product.is_parent_bulk
    ):
        return True
    if 'parent_bulk_product' in data and _parent_id_differs(
        data['parent_bulk_product'], product.parent_bulk_product_id
    ):
        return True
    return False


def create_payload_sets_pack_link(data):
    """True when create body would set a pack link away from defaults."""
    if not isinstance(data, dict):
        return False
    if 'conversion_factor' in data and data['conversion_factor'] not in (None, ''):
        return True
    if 'parent_bulk_product' in data and data['parent_bulk_product'] not in (None, ''):
        return True
    if 'is_parent_bulk' in data and _as_bool(data['is_parent_bulk']):
        return True
    return False


UNPARSEABLE_EXPIRY = object()
_UNPARSEABLE_DATE = UNPARSEABLE_EXPIRY


def parse_expiry_date(raw):
    return _parse_expiry_date(raw)


def _parse_expiry_date(raw):
    if raw in (None, ''):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return _UNPARSEABLE_DATE


def _expiry_differs(raw, current):
    parsed = _parse_expiry_date(raw)
    if parsed is _UNPARSEABLE_DATE:
        return True
    if current is None:
        return parsed is not None
    return parsed != current


def payload_has_invalid_expiry(data):
    """True when any batches[].expiry_date cannot be parsed as a date."""
    batches = _parse_batches(data)
    if not batches:
        return False
    return any(
        isinstance(batch, dict)
        and 'expiry_date' in batch
        and _parse_expiry_date(batch.get('expiry_date')) is UNPARSEABLE_EXPIRY
        for batch in batches
    )


def payload_sets_batch_expiry(data):
    """True when any batches[].expiry_date key is present."""
    batches = _parse_batches(data)
    if not batches:
        return False
    return any(
        isinstance(batch, dict) and 'expiry_date' in batch
        for batch in batches
    )


def submitted_batch_expiry_differs(product, data):
    """True when submitted batch expiry would change stored values."""
    batches = _parse_batches(data)
    if not batches or product is None:
        return False
    batch_ids = [
        batch.get('id')
        for batch in batches
        if isinstance(batch, dict) and 'expiry_date' in batch and batch.get('id')
    ]
    existing = {}
    if batch_ids:
        existing = {
            row.id: row.expiry_date
            for row in product.batches.filter(id__in=batch_ids).only(
                'id', 'expiry_date'
            )
        }
    for batch in batches:
        if not isinstance(batch, dict) or 'expiry_date' not in batch:
            continue
        batch_id = batch.get('id')
        if not batch_id:
            parsed = _parse_expiry_date(batch.get('expiry_date'))
            if parsed is _UNPARSEABLE_DATE or parsed is not None:
                return True
            continue
        try:
            batch_id = int(batch_id)
        except (TypeError, ValueError):
            return True
        if batch_id not in existing:
            return True
        if _expiry_differs(batch.get('expiry_date'), existing[batch_id]):
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
