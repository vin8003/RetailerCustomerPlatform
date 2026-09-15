"""
OE-100 / F-0041 — supplier master EXTEND (GSTIN, payment terms, inactive gate).

Keeps ``retailers.Supplier`` as the only vendor master. ``products.SupplierLedger``
is unchanged. Purchase-invoice create is the current inward path; PO/GRN
three-way match is OE-102 and should call
``assert_supplier_selectable_for_new_purchase``.
"""
import re

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from retailers.models import OrgAuditLog, RetailerProfile, Supplier, UNIQ_ORG_SUPPLIER_GSTIN
from retailers.organization import (
    ensure_org_rbac_bootstrap,
    get_organization_for_user,
    user_has_org_permission,
)

PERM_PURCHASING_TERMS = 'purchasing.terms'

GSTIN_PATTERN = re.compile(
    r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
)
GSTIN_FORMAT_MESSAGE = (
    'Invalid GSTIN format. It should be like: 22AAAAA0000A1Z5 (15 characters).'
)
DUPLICATE_GSTIN_MESSAGE = (
    'GSTIN already used by another supplier in this organization.'
)
PAYMENT_TERMS_WHITESPACE_MESSAGE = (
    'Payment terms cannot be whitespace-only.'
)
INACTIVE_SUPPLIER_MESSAGE = (
    'Inactive suppliers cannot be selected on new purchase documents.'
)
INVALID_SUPPLIER_ORG_MESSAGE = 'Invalid supplier for this organization.'

_MISSING = object()


def normalize_gstin(value):
    """
    Strip and uppercase GSTIN. Blank stays blank.

    Raises ValidationError when a non-blank value is not a 15-char GSTIN.
    """
    raw = (value or '').strip().upper()
    if not raw:
        return ''
    if not GSTIN_PATTERN.match(raw):
        raise ValidationError(GSTIN_FORMAT_MESSAGE)
    return raw


def org_suppliers_queryset(organization):
    """Suppliers attached to any shop location of this org (no N+1)."""
    if organization is None:
        return Supplier.objects.none()
    return Supplier.objects.filter(retailer__organization=organization)


def active_suppliers_for_org(organization):
    """Picker queryset for new POs / purchase invoices (OE-102 hook)."""
    return org_suppliers_queryset(organization).filter(is_active=True)


def gstin_exists_in_org(organization, gstin, exclude_id=None):
    """True when another supplier in the org already has this non-blank GSTIN."""
    if organization is None or not gstin:
        return False
    qs = org_suppliers_queryset(organization).filter(gst_number=gstin)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def duplicate_gstin_error():
    return ValidationError({
        'gst_number': [DUPLICATE_GSTIN_MESSAGE],
        'gstin_duplicate': True,
    })


def map_gstin_integrity_error(exc):
    """Map the org GSTIN unique constraint to the same 400 the app check uses."""
    text = str(exc)
    lowered = text.lower()
    if UNIQ_ORG_SUPPLIER_GSTIN in text:
        raise duplicate_gstin_error() from exc
    if (
        'unique' in lowered
        and 'gst_number' in lowered
        and 'organization' in lowered
    ):
        raise duplicate_gstin_error() from exc
    raise exc


def normalize_payment_terms(value):
    """
    Trim payment terms. None/empty stays empty.

    Whitespace-only is invalid when the field is being set.
    """
    if value is None:
        return ''
    text = str(value)
    stripped = text.strip()
    if text and not stripped:
        raise ValidationError(PAYMENT_TERMS_WHITESPACE_MESSAGE)
    return stripped


def payment_terms_are_whitespace_only(data):
    if not isinstance(data, dict) or 'payment_terms' not in data:
        return False
    raw = data.get('payment_terms')
    if raw is None:
        return False
    text = str(raw)
    return bool(text) and not text.strip()


def assert_payment_terms_not_whitespace_only(data):
    """Raise 400 when payment_terms is present and whitespace-only."""
    if payment_terms_are_whitespace_only(data):
        raise ValidationError({'payment_terms': [PAYMENT_TERMS_WHITESPACE_MESSAGE]})


def resolve_supplier_home_retailer(user):
    """
    Shop location to attach a newly created supplier.

    Owner path: their RetailerProfile. Staff path: first location of their org.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    profile = (
        RetailerProfile.objects.select_related('organization')
        .filter(user=user)
        .first()
    )
    if profile is not None:
        return profile
    org = get_organization_for_user(user)
    if org is None:
        return None
    return (
        RetailerProfile.objects.select_related('organization')
        .filter(organization=org)
        .order_by('id')
        .first()
    )


def submitted_payment_terms(data):
    if not isinstance(data, dict) or 'payment_terms' not in data:
        return _MISSING
    raw = data.get('payment_terms')
    if raw is None:
        return ''
    return str(raw).strip()


def payment_terms_would_change(instance, data):
    """True when the body sets payment_terms to a value other than stored/blank."""
    submitted = submitted_payment_terms(data)
    if submitted is _MISSING:
        return False
    if instance is None:
        return bool(submitted)
    current = (instance.payment_terms or '').strip()
    return submitted != current


def purchasing_terms_denied_response():
    return Response(
        {'error': 'Payment terms may only be changed by a purchase-role user'},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_purchasing_terms(user, organization=None, *, changing):
    """
    Return a 403/404 Response when the user may not change payment terms.

    Echoing the current value (or omitting the field / blank create) is allowed.
    Owner is implicit admin. On deny, refresh system Admin then re-check.
    """
    if not changing:
        return None
    org = organization
    if org is None:
        org = get_organization_for_user(user)
    if org is None:
        return Response(
            {'error': 'Organization not found or access denied'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if user_has_org_permission(user, org, PERM_PURCHASING_TERMS):
        return None
    ensure_org_rbac_bootstrap(org)
    if user_has_org_permission(user, org, PERM_PURCHASING_TERMS):
        return None
    return purchasing_terms_denied_response()


def assert_supplier_selectable_for_new_purchase(supplier):
    """
    Inactive suppliers cannot be selected on new POs or purchase invoices.

    Call from purchase-invoice create / supplier-change and from OE-102 PO create.
    """
    if supplier is not None and not supplier.is_active:
        raise ValidationError({'supplier': INACTIVE_SUPPLIER_MESSAGE})


def assert_supplier_in_org(supplier, retailer):
    """Reject a supplier that does not belong to the invoice shop's organization."""
    if supplier is None or retailer is None:
        return
    org_id = getattr(retailer, 'organization_id', None)
    if org_id:
        supplier_org_id = getattr(
            getattr(supplier, 'retailer', None), 'organization_id', None
        )
        if supplier_org_id is None and supplier.retailer_id:
            supplier_org_id = (
                RetailerProfile.objects.filter(pk=supplier.retailer_id)
                .values_list('organization_id', flat=True)
                .first()
            )
        if supplier_org_id == org_id:
            return
        raise ValidationError({'supplier': INVALID_SUPPLIER_ORG_MESSAGE})
    if supplier.retailer_id != retailer.id:
        raise ValidationError({'supplier': INVALID_SUPPLIER_ORG_MESSAGE})


def record_payment_terms_audit(user, supplier, before, after):
    """Append OrgAuditLog when payment terms actually change."""
    if supplier is None:
        return None
    before_val = (before or '').strip()
    after_val = (after or '').strip()
    if before_val == after_val:
        return None
    retailer = getattr(supplier, 'retailer', None)
    org = getattr(retailer, 'organization', None) if retailer is not None else None
    if org is None:
        return None
    from retailers.audit_log import record_org_audit_event

    return record_org_audit_event(
        organization=org,
        actor=user,
        action=OrgAuditLog.ACTION_UPDATE,
        object_type=OrgAuditLog.OBJECT_SUPPLIER,
        object_id=supplier.id,
        summary_before={'payment_terms': before_val},
        summary_after={'payment_terms': after_val},
        location=retailer,
    )
