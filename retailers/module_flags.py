"""
Org-scoped shop module flags (OE-101 / F-0004).

Flags are readable by any same-tenant retailer for nav hiding; enforcement
is server-side on gated APIs via ``require_module_enabled``.
"""
from rest_framework import status
from rest_framework.response import Response

from .models import OrgModuleFlags
from .module_flags_catalog import (
    ALL_MODULE_CODES,
    ERROR_CODE_MODULE_DISABLED,
    default_module_flags,
    is_known_module,
)


def ensure_org_module_flags(organization):
    """
    Ensure an OrgModuleFlags row exists with all modules enabled.

    Idempotent. Called from org RBAC bootstrap.
    """
    if organization is None:
        return None
    row, _created = OrgModuleFlags.objects.get_or_create(
        organization=organization,
        defaults={'flags': default_module_flags()},
    )
    return row


def get_module_flags_dict(organization):
    """Return normalized module flags for an org (creates row if missing)."""
    row = ensure_org_module_flags(organization)
    base = default_module_flags()
    stored = row.flags or {}
    for code in ALL_MODULE_CODES:
        if code in stored and isinstance(stored[code], bool):
            base[code] = stored[code]
    return base


def is_module_enabled(organization, module_code):
    """True when the module is enabled for this org."""
    if not is_known_module(module_code):
        return True
    flags = get_module_flags_dict(organization)
    return bool(flags.get(module_code, True))


def module_disabled_response(module_code):
    """403 response with stable error_code for a disabled module."""
    return Response(
        {
            'error': f'Module {module_code} is disabled for this organization',
            'error_code': ERROR_CODE_MODULE_DISABLED,
            'module': module_code,
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def require_module_enabled(user, module_code):
    """
    Resolve caller org and verify module is enabled.

    Returns (organization, None) when allowed, or (None, Response) on deny.
    """
    from .organization import get_organization_for_user

    org = get_organization_for_user(user)
    if org is None:
        return None, Response(
            {'error': 'Retailer profile not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if not is_module_enabled(org, module_code):
        return None, module_disabled_response(module_code)
    return org, None
