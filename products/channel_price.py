"""
OE-106 / F-0023 — store vs owned-app selling price (thin EXTEND).

``Product.price`` stays the store / POS list. ``Product.app_price`` is the
owned-app list; null means fall back to store price. One ATP pool is
unchanged (``Product.quantity`` / saleable). No PriceList engine (F-0022)
and no marketplace connector.
"""
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.fields import DecimalField
from rest_framework.response import Response

from retailers.models import OrgAuditLog
from retailers.organization import (
    ensure_org_rbac_bootstrap,
    get_organization_for_user,
    user_has_org_permission,
)

CHANNEL_STORE = 'store'
CHANNEL_APP = 'app'
PERM_CATALOG_PRICE = 'catalog.price'

_MONEY = DecimalField(max_digits=10, decimal_places=2)


def resolve_channel_price(product, channel, batch=None):
    """Selling Decimal for a channel. App uses Product.app_price when set."""
    if channel == CHANNEL_APP and getattr(product, 'app_price', None) is not None:
        return product.app_price
    if batch is not None and getattr(batch, 'price', None) is not None:
        return batch.price
    return product.price


def price_channel_from_request(request):
    """
    Retailer JWT on shop APIs sees the store list. Everyone else (customer,
    anonymous, missing request) sees the app list. Fail closed: do not leak
    store-only fields on an unknown caller.
    """
    if request is None:
        return CHANNEL_APP
    user = getattr(request, 'user', None)
    if (
        user is not None
        and getattr(user, 'is_authenticated', False)
        and getattr(user, 'user_type', None) == 'retailer'
    ):
        return CHANNEL_STORE
    return CHANNEL_APP


def format_money(value):
    if value is None:
        return None
    return _MONEY.to_representation(value)


def apply_channel_price_representation(data, product, context):
    """Rewrite shared product payloads so app callers cannot read store list."""
    if not isinstance(data, dict) or product is None:
        return data
    channel = (context or {}).get('price_channel')
    if channel is None:
        channel = price_channel_from_request((context or {}).get('request'))
    selling = resolve_channel_price(product, channel)
    formatted = format_money(selling)
    data['price'] = formatted
    if 'discounted_price' in data:
        data['discounted_price'] = formatted
    if channel == CHANNEL_APP:
        data.pop('app_price', None)
    else:
        data['app_price'] = format_money(getattr(product, 'app_price', None))
    return data


def _money_differs(raw, current):
    if raw in (None, ''):
        return current is not None
    try:
        submitted = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return True
    if current is None:
        return True
    return submitted != Decimal(str(current))


def payload_sets_app_price(data):
    return isinstance(data, dict) and 'app_price' in data


def submitted_app_price_differs(product, data):
    if not payload_sets_app_price(data) or product is None:
        return False
    return _money_differs(data.get('app_price'), getattr(product, 'app_price', None))


def create_payload_sets_app_price(data):
    if not payload_sets_app_price(data):
        return False
    return data.get('app_price') not in (None, '')


def bulk_items_set_app_price(items):
    if not isinstance(items, list):
        return False
    return any(payload_sets_app_price(item) for item in items)


def bulk_items_would_change_app_price(items, products_by_id):
    if not isinstance(items, list):
        return False
    for item in items:
        if not payload_sets_app_price(item):
            continue
        product = products_by_id.get(item.get('id'))
        if product is None:
            return True
        if _money_differs(item.get('app_price'), product.app_price):
            return True
    return False


def catalog_price_denied_response():
    return Response(
        {'error': 'Catalog price permission required'},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_catalog_price(user, organization=None):
    """
    Return a 403/404 Response when the user may not change app_price.

    Owner is implicit admin. On deny, refresh system Admin from the catalog
    then re-check so stale admin roles do not block after a catalog bump.
    """
    org = organization
    if org is None:
        org = get_organization_for_user(user)
    if org is None:
        return Response(
            {'error': 'Organization not found or access denied'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if user_has_org_permission(user, org, PERM_CATALOG_PRICE):
        return None
    ensure_org_rbac_bootstrap(org)
    if user_has_org_permission(user, org, PERM_CATALOG_PRICE):
        return None
    return catalog_price_denied_response()


def app_price_summary(product, app_price=None):
    if app_price is None and product is not None:
        app_price = product.app_price
    return {
        'product_id': product.id if product is not None else None,
        'store_price': format_money(product.price) if product is not None else None,
        'app_price': format_money(app_price),
    }


def record_channel_price_audit(
    *,
    product,
    actor,
    organization,
    location=None,
    summary_before=None,
    summary_after=None,
    action=OrgAuditLog.ACTION_UPDATE,
):
    if organization is None or product is None:
        return None
    before = dict(summary_before or {})
    after = dict(summary_after or {})
    if before == after:
        return None
    from retailers.audit_log import record_org_audit_event

    return record_org_audit_event(
        organization=organization,
        actor=actor,
        action=action,
        object_type=OrgAuditLog.OBJECT_CHANNEL_PRICE,
        object_id=product.id,
        summary_before=before,
        summary_after=after,
        location=location,
    )
