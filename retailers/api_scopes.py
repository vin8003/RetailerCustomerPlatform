"""
Versioned partner API scope catalog (OE-182 / F-0006).

Deny-by-default: only codes listed here may be stored on an OrgApiKey.
Partner routes require an exact granted scope; missing scope → 403.
"""

API_SCOPE_CATALOG_VERSION = 1

# code -> human description
API_SCOPE_DEFINITIONS = {
    'partner.org.read': 'Read organization metadata for the key tenant',
    'partner.org.write': 'Update organization name for the key tenant',
    'partner.locations.read': 'List shop locations belonging to the key tenant',
}

ALL_API_SCOPE_CODES = frozenset(API_SCOPE_DEFINITIONS.keys())


def is_known_scope(code: str) -> bool:
    return code in ALL_API_SCOPE_CODES


def validate_scope_codes(codes):
    """
    Return (normalized_list, unknown_list).

    Normalized list is sorted unique known codes. Unknown codes are rejected
    by callers on key create/update.
    """
    if codes is None:
        return [], []
    if not isinstance(codes, (list, tuple, set)):
        raise TypeError('scopes must be a list of strings')
    unknown = []
    known = set()
    for raw in codes:
        if not isinstance(raw, str) or not raw:
            unknown.append(raw)
            continue
        if raw in ALL_API_SCOPE_CODES:
            known.add(raw)
        else:
            unknown.append(raw)
    return sorted(known), unknown


def scope_catalog_payload():
    """API-friendly snapshot of the versioned partner scope catalog."""
    return {
        'version': API_SCOPE_CATALOG_VERSION,
        'scopes': [
            {'code': code, 'description': desc}
            for code, desc in sorted(API_SCOPE_DEFINITIONS.items())
        ],
    }
