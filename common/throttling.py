"""
Rate limiting for org-scoped partner API keys (OE-182 / F-0006).
"""
from rest_framework.throttling import SimpleRateThrottle

from common.authentication import get_request_api_key


class OrgApiKeyRateThrottle(SimpleRateThrottle):
    """Throttle partner traffic per API key prefix."""
    scope = 'api_key'

    def get_cache_key(self, request, view):
        api_key = get_request_api_key(request)
        if api_key is None:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': api_key.prefix,
        }
