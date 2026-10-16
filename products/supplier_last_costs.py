"""
OE-112 / F-0045 — last supplier costs for a SKU from purchase-invoice history.
OE-118 / F-0046 — purchase-role margin% preview from draft-or-last PI cost.
OE-169 / F-0071 — same margin% on purchase-role catalog list/detail/search.
OE-284 / F-0071 follow-on — same field on POS no_page.

Thin EXTEND: read existing PurchaseItem.purchase_price + invoice.supplier,
and Product.price / Product.purchase_price. No PO, quote, policy, or
cost-model tables. Missing history/cost stays empty/null (not 0).
Purchase-role gate reuses purchasing.terms (OE-100).
"""
from decimal import Decimal

from django.db.models import OuterRef, Subquery
from rest_framework import status
from rest_framework.response import Response

from products.models import Product, PurchaseItem
from retailers.models import Supplier
from retailers.organization import (
    ensure_org_rbac_bootstrap,
    get_organization_for_user,
    user_has_org_permission,
)

# Seeing what the shop pays suppliers is margin information; it has its own permission.
PERM_PURCHASE_ROLE = 'purchasing.costs.read'

PURCHASE_ROLE_COST_DENIED = (
    'Supplier costs may only be viewed by a purchase-role user'
)


def purchase_role_denied_response():
    return Response(
        {'error': PURCHASE_ROLE_COST_DENIED},
        status=status.HTTP_403_FORBIDDEN,
    )


def include_purchase_margin(user, organization=None):
    """True when catalog reads may include margin_percent."""
    return require_purchase_role(user, organization=organization) is None


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


def _latest_pi_lines(**filters):
    """PurchaseItems newest first: invoice_date, created_at, then item id."""
    return PurchaseItem.objects.filter(**filters).order_by(
        '-invoice__invoice_date',
        '-invoice__created_at',
        '-pk',
    )


def last_supplier_cost_rows_for_product(product):
    """
    Latest PurchaseItem.purchase_price per supplier for this shop SKU.

    One query, one row per supplier (correlated subqueries, so the SKU's
    full purchase history is never loaded). Suppliers without a line are
    omitted — callers must not invent 0.
    """
    lines = {'product_id': product.id, 'invoice__retailer_id': product.retailer_id}
    latest = _latest_pi_lines(invoice__supplier_id=OuterRef('pk'), **lines)
    suppliers = (
        Supplier.objects.filter(
            pk__in=PurchaseItem.objects.filter(**lines).values('invoice__supplier_id')
        )
        .annotate(
            last_cost=Subquery(latest.values('purchase_price')[:1]),
            last_invoice_id=Subquery(latest.values('invoice_id')[:1]),
            last_invoice_date=Subquery(latest.values('invoice__invoice_date')[:1]),
        )
        .values_list('pk', 'company_name', 'last_cost', 'last_invoice_id', 'last_invoice_date')
    )
    rows = [
        {
            'supplier_id': supplier_id,
            'supplier_name': company_name or '',
            'last_cost': last_cost,
            'invoice_id': invoice_id,
            'invoice_date': invoice_date,
        }
        for supplier_id, company_name, last_cost, invoice_id, invoice_date in suppliers
    ]
    rows.sort(key=lambda row: ((row['supplier_name'] or '').lower(), row['supplier_id']))
    return rows


def last_pi_unit_cost_for_product(product):
    """
    Latest PurchaseItem.purchase_price for this shop SKU, or None.

    One query. Missing history stays None — callers must not invent 0.
    A stored 0.00 line is real history and is returned.
    """
    return (
        _latest_pi_lines(product_id=product.id, invoice__retailer_id=product.retailer_id)
        .values_list('purchase_price', flat=True)
        .first()
    )


def last_pi_unit_costs_by_product_id(products):
    """
    Latest PurchaseItem.purchase_price per SKU that has no draft cost.

    One query, one row per SKU (correlated subquery, so purchase history is
    never loaded). SKUs with a draft purchase_price or no PI history are
    omitted — callers must not invent 0. A stored 0.00 line is returned.
    """
    ids = [product.id for product in products if product.purchase_price is None]
    if not ids:
        return {}
    latest = _latest_pi_lines(
        product_id=OuterRef('pk'),
        invoice__retailer_id=OuterRef('retailer_id'),
    ).values('purchase_price')[:1]
    rows = (
        Product.objects.filter(id__in=ids)
        .annotate(last_pi_cost=Subquery(latest))
        .values_list('id', 'last_pi_cost')
    )
    return {product_id: cost for product_id, cost in rows if cost is not None}


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
