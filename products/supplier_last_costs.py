"""
OE-112 / F-0045 — last supplier costs for a SKU from purchase-invoice history.

Thin EXTEND: read existing PurchaseItem.purchase_price + invoice.supplier.
No PO, quote, or cost-model tables. Missing history stays empty (not 0).
Purchase-role gate reuses purchasing.terms (OE-100).
"""
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
