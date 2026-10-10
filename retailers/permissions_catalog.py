"""
Versioned shop staff permission catalog (OE-98 / F-0002 / S-0002A).

Deny-by-default: only codes listed here may be stored on a role.
Org owner always has every permission (implicit admin) until they delegate.
"""

PERMISSION_CATALOG_VERSION = 1

# code -> human description
PERMISSION_DEFINITIONS = {
    'org.update': 'Update organization name and active flag',
    'roles.manage': 'Create and edit named roles and their permission lists',
    'staff.manage': 'Assign, change, and revoke staff memberships and roles',
}

ALL_PERMISSION_CODES = frozenset(PERMISSION_DEFINITIONS.keys())

ROLE_SLUG_ADMIN = 'admin'
ROLE_SLUG_CASHIER = 'cashier'

# Bootstrap templates: admin gets everything; cashier gets none (deny-by-default).
BOOTSTRAP_ROLES = (
    {
        'slug': ROLE_SLUG_ADMIN,
        'name': 'Admin',
        'permissions': sorted(ALL_PERMISSION_CODES),
        'is_system': True,
    },
    {
        'slug': ROLE_SLUG_CASHIER,
        'name': 'Cashier',
        'permissions': [],
        'is_system': True,
    },
)


def is_known_permission(code: str) -> bool:
    return code in ALL_PERMISSION_CODES


def validate_permission_codes(codes):
    """
    Return (normalized_list, unknown_list).

    Normalized list is sorted unique known codes. Unknown codes are rejected
    by callers on role save.
    """
    if codes is None:
        return [], []
    if not isinstance(codes, (list, tuple, set)):
        raise TypeError('permissions must be a list of strings')
    unknown = []
    known = set()
    for raw in codes:
        if not isinstance(raw, str) or not raw:
            unknown.append(raw)
            continue
        if raw in ALL_PERMISSION_CODES:
            known.add(raw)
        else:
            unknown.append(raw)
    return sorted(known), unknown


def catalog_payload():
    """API-friendly snapshot of the versioned catalog."""
    return {
        'version': PERMISSION_CATALOG_VERSION,
        'permissions': [
            {'code': code, 'description': desc}
            for code, desc in sorted(PERMISSION_DEFINITIONS.items())
        ],
    }
