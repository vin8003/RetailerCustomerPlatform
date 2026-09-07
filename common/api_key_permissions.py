"""
DRF permission helpers for partner API key scopes (OE-182 / F-0006).
"""
from rest_framework.permissions import BasePermission

from common.authentication import get_request_api_key, is_api_key_principal


class HasApiKeyScope(BasePermission):
    """
    Require an authenticated org API key that holds ``required_scope``.

    Prefer subclassing with ``required_scope`` set, or set
    ``view.required_scope`` before the permission check.
    Missing/wrong auth → handled by authentication (401). Missing scope → 403.
    """
    message = 'API key lacks the required scope.'
    required_scope = None

    def has_permission(self, request, view):
        required = getattr(view, 'required_scope', None) or self.required_scope
        if not required:
            self.message = 'Partner route is missing a required_scope declaration.'
            return False

        if not is_api_key_principal(request.user):
            return False

        api_key = get_request_api_key(request)
        if api_key is None:
            return False
        # Live re-read so a revoke mid-flight is still rejected.
        api_key.refresh_from_db(fields=['is_active', 'scopes'])
        if not api_key.is_active:
            return False
        if required not in (api_key.scopes or []):
            self.message = f'API key lacks required scope: {required}'
            return False
        return True


def require_api_scope(scope_code: str):
    """Build a permission class that requires a specific partner scope."""

    class _Scoped(HasApiKeyScope):
        required_scope = scope_code

    _Scoped.__name__ = f'RequireApiScope_{scope_code.replace(".", "_")}'
    return _Scoped


class IsOrgApiKeyManager(BasePermission):
    """JWT retailer with ``api_keys.manage`` (org owner always qualifies)."""
    message = 'API key management permission required.'

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'user_type', None) == 'retailer'
        )
