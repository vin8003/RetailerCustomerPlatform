"""
Partner API key authentication (OE-182 / F-0006).

Accepts:
  Authorization: Api-Key <raw_key>
  X-Api-Key: <raw_key>

JWT / session clients are unaffected — this class returns None when no
API-key header is present so other authenticators can run.
"""
from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication, exceptions


class ApiKeyPrincipal:
    """
    Authenticated principal for org-scoped partner API keys.

    Not an AUTH_USER_MODEL row — partners are machine credentials, not staff.
    """
    is_authenticated = True
    is_anonymous = False
    is_active = True
    user_type = 'api_key'
    pk = None
    id = None
    username = ''

    def __init__(self, api_key):
        self.api_key = api_key
        self.organization = api_key.organization
        self.username = f"api_key:{api_key.prefix}"

    def __str__(self):
        return self.username


class OrgApiKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticate partner requests with an org-scoped API key.

    Revoked keys are rejected on the next request (live DB is_active check).
    """
    keyword = 'Api-Key'
    header_name = 'HTTP_X_API_KEY'

    def authenticate(self, request):
        raw = self._extract_raw_key(request)
        if not raw:
            return None

        from retailers.api_keys import authenticate_api_key, touch_api_key_last_used

        api_key = authenticate_api_key(raw)
        if api_key is None:
            raise exceptions.AuthenticationFailed('Invalid or revoked API key')

        touch_api_key_last_used(api_key)
        principal = ApiKeyPrincipal(api_key)
        return (principal, api_key)

    def authenticate_header(self, request):
        return self.keyword

    def _extract_raw_key(self, request):
        auth = authentication.get_authorization_header(request).decode('utf-8', errors='ignore')
        if auth:
            parts = auth.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == self.keyword.lower():
                return parts[1].strip() or None
            # Bearer / other schemes — leave for JWT authenticator
            if len(parts) >= 1 and parts[0].lower() != self.keyword.lower():
                return None

        raw = request.META.get(self.header_name, '').strip()
        return raw or None


def get_request_api_key(request):
    """Return OrgApiKey from request.auth when authenticated via API key."""
    auth = getattr(request, 'auth', None)
    if auth is None:
        return None
    from retailers.models import OrgApiKey
    if isinstance(auth, OrgApiKey):
        return auth
    return None


def is_api_key_principal(user):
    return isinstance(user, ApiKeyPrincipal) or (
        getattr(user, 'user_type', None) == 'api_key'
        and not isinstance(user, AnonymousUser)
    )
