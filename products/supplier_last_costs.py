"""
OE-112 / F-0045 — last supplier costs for a SKU from purchase-invoice history.
OE-118 / F-0046 — purchase-role margin% preview from draft-or-last PI cost.

Thin EXTEND: read existing PurchaseItem.purchase_price + invoice.supplier,
and Product.price / Product.purchase_price. No PO, quote, policy, or
cost-model tables. Missing history/cost stays empty/null (not 0).
Purchase-role gate reuses purchasing.terms (OE-100).
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.response import Response

from products.models import PurchaseItem
from retailers.organization import (
    ensure_org_rbac_bootstrap,
    get_organization_for_user,
    user_has_org_permission,
)
from retailers.suppliers import PERM_PURCHASING_TERMS

PERM_PURCHASE_ROLE = PERM_PURCHASING_TERMS

PURCHASE_ROLE_COST_DENIED = (
    'Supplier costs may only be viewed by a purchase-role user'
)


def purchase_role_denied_response():
    return Response(
        {'error': PURCHASE_ROLE_COST_DENIED},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_purchase_role(user, organization=None):
    """
    Return a 403/404 Response when the user is not purchase-role.

    Owner is implicit admin. On deny, refresh system Admin then re-check
    so stale OrgRole(admin).permissions do not block admin staff.
    """
    org = organization
    if org is None:
        org = get_organization_for_user(user)
    if org is None:
        return Response(
            {'error': 'Organization not found or access denied'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if user_has_org_permission(user, org, PERM_PURCHASE_ROLE):
        return None
    ensure_org_rbac_bootstrap(org)
    if user_has_org_permission(user, org, PERM_PURCHASE_ROLE):
        return None
    return purchase_role_denied_response()


def last_supplier_cost_rows_for_product(product):
    """
    Latest PurchaseItem.purchase_price per supplier for this shop SKU.

    One query (select_related). First row per supplier after ordering by
    invoice_date, created_at, then item id. Suppliers without a line are
    omitted — callers must not invent 0.
    """
    items = (
        PurchaseItem.objects.filter(
            product_id=product.id,
            invoice__retailer_id=product.retailer_id,
            invoice__supplier_id__isnull=False,
        )
        .select_related('invoice', 'invoice__supplier')
        .order_by(
            'invoice__supplier_id',
            '-invoice__invoice_date',
            '-invoice__created_at',
            '-pk',
        )
    )
    seen = set()
    rows = []
    for item in items:
        supplier_id = item.invoice.supplier_id
        if supplier_id in seen:
            continue
        seen.add(supplier_id)
        supplier = item.invoice.supplier
        rows.append({
            'supplier_id': supplier_id,
            'supplier_name': supplier.company_name if supplier else '',
            'last_cost': item.purchase_price,
            'invoice_id': item.invoice_id,
            'invoice_date': item.invoice.invoice_date,
        })
    rows.sort(key=lambda row: ((row['supplier_name'] or '').lower(), row['supplier_id']))
    return rows


def last_pi_unit_cost_for_product(product):
    """
    Latest PurchaseItem.purchase_price for this shop SKU, or None.

    One query. Missing history stays None — callers must not invent 0.
    A stored 0.00 line is real history and is returned.
    """
    return (
        PurchaseItem.objects.filter(
            product_id=product.id,
            invoice__retailer_id=product.retailer_id,
        )
        .order_by(
            '-invoice__invoice_date',
            '-invoice__created_at',
            '-pk',
        )
        .values_list('purchase_price', flat=True)
        .first()
    )


def draft_or_last_pi_cost(product):
    """
    SKU purchase_price (draft) if set, else last PI unit cost.

    Returns (cost, source) where source is 'draft', 'last_pi', or None.
    Missing stays (None, None) — callers must not invent 0.
    """
    if product.purchase_price is not None:
        return product.purchase_price, 'draft'
    last = last_pi_unit_cost_for_product(product)
    if last is None:
        return None, None
    return last, 'last_pi'


def selling_margin_percent(selling_price, cost):
    """
    Gross margin % = (sell - cost) / sell * 100.

    Missing cost or zero/absent sell → None (not 0).
    """
    if cost is None or selling_price is None:
        return None
    sell = Decimal(selling_price)
    if sell == 0:
        return None
    return ((sell - Decimal(cost)) * Decimal('100') / sell).quantize(
        Decimal('0.01')
    )
