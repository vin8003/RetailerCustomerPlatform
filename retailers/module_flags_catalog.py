"""
Versioned shop module flag catalog (OE-101 / F-0004).

Each module can be enabled or disabled per organization. Disabled modules
return 403 with a stable ``module_disabled`` error code on gated APIs.
Commercial packaging attaches here without a second engine.
"""

MODULE_CATALOG_VERSION = 1

# code -> human description
MODULE_DEFINITIONS = {
    'catalog': 'Product catalog and inventory management',
    'orders': 'Order processing and fulfillment',
    'customers': 'Customer CRM and credit (khata)',
    'rewards': 'Loyalty and referral rewards configuration',
}

ALL_MODULE_CODES = frozenset(MODULE_DEFINITIONS.keys())

# Stable machine-readable code for disabled-module 403 responses.
ERROR_CODE_MODULE_DISABLED = 'module_disabled'


def default_module_flags():
    """All known modules enabled — safe bootstrap default."""
    return {code: True for code in sorted(ALL_MODULE_CODES)}


def is_known_module(code: str) -> bool:
    return code in ALL_MODULE_CODES


def validate_module_flags(raw):
    """
    Return (normalized_dict, unknown_list).

    Only known module codes are accepted. Values must be booleans.
    """
    if raw is None:
        return default_module_flags(), []
    if not isinstance(raw, dict):
        raise TypeError('flags must be a dict of module_code -> bool')
    unknown = []
    normalized = default_module_flags()
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            unknown.append(key)
            continue
        if key not in ALL_MODULE_CODES:
            unknown.append(key)
            continue
        if not isinstance(value, bool):
            raise TypeError(f'flag for {key} must be a boolean')
        normalized[key] = value
    return normalized, unknown


def catalog_payload():
    """API-friendly snapshot of the versioned module catalog."""
    return {
        'version': MODULE_CATALOG_VERSION,
        'modules': [
            {'code': code, 'description': desc}
            for code, desc in sorted(MODULE_DEFINITIONS.items())
        ],
    }
