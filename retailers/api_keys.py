"""
Org-scoped partner API key helpers (OE-182 / F-0006).

Keys are hashed at rest. Authentication re-reads is_active from the DB on
every request so revoke takes effect immediately.
"""
import hashlib
import hmac
import secrets

from django.db import transaction
from django.utils import timezone

from .api_scopes import ALL_API_SCOPE_CODES, validate_scope_codes
from .models import OrgApiKey, OrgApiKeyAudit


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


def generate_raw_api_key():
    """
    Return (raw_key, prefix, key_hash).

    Format: oe_<prefix>_<secret>. Prefix is public; full raw key shown once.
    """
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw = f"oe_{prefix}_{secret}"
    return raw, prefix, hash_api_key(raw)


def parse_key_prefix(raw_key: str):
    """Extract public prefix from a raw key, or None if malformed."""
    if not raw_key or not isinstance(raw_key, str):
        return None
    parts = raw_key.strip().split('_', 2)
    if len(parts) != 3 or parts[0] != 'oe' or not parts[1]:
        return None
    return parts[1]


def verify_raw_key(raw_key: str, key_hash: str) -> bool:
    if not raw_key or not key_hash:
        return False
    return hmac.compare_digest(hash_api_key(raw_key), key_hash)


def create_org_api_key(*, organization, name, scopes, created_by=None):
    """
    Create an active OrgApiKey. Returns (api_key, raw_key).

    ``raw_key`` is returned once and never stored.
    """
    known, unknown = validate_scope_codes(scopes)
    if unknown:
        raise ValueError(f'Unknown API scope codes: {unknown}')

    with transaction.atomic():
        raw, prefix, key_hash = generate_raw_api_key()
        # Extremely unlikely collision; regenerate once.
        if OrgApiKey.objects.filter(prefix=prefix).exists():
            raw, prefix, key_hash = generate_raw_api_key()

        api_key = OrgApiKey.objects.create(
            organization=organization,
            name=name.strip(),
            prefix=prefix,
            key_hash=key_hash,
            scopes=known,
            is_active=True,
            created_by=created_by if getattr(created_by, 'is_authenticated', False) else None,
        )
        record_api_key_audit(
            organization=organization,
            api_key=api_key,
            actor=created_by,
            action=OrgApiKeyAudit.ACTION_GRANT,
            scopes_before=[],
            scopes_after=known,
        )
        return api_key, raw


def revoke_org_api_key(*, api_key, actor=None):
    """Soft-revoke; next partner request with this key is rejected."""
    if not api_key.is_active and api_key.revoked_at is not None:
        return api_key

    scopes_before = list(api_key.scopes or [])
    api_key.is_active = False
    api_key.revoked_at = timezone.now()
    api_key.save(update_fields=['is_active', 'revoked_at', 'updated_at'])
    record_api_key_audit(
        organization=api_key.organization,
        api_key=api_key,
        actor=actor,
        action=OrgApiKeyAudit.ACTION_REVOKE,
        scopes_before=scopes_before,
        scopes_after=[],
    )
    return api_key


def update_org_api_key_scopes(*, api_key, scopes, actor=None):
    known, unknown = validate_scope_codes(scopes)
    if unknown:
        raise ValueError(f'Unknown API scope codes: {unknown}')
    scopes_before = list(api_key.scopes or [])
    if scopes_before == known:
        return api_key
    api_key.scopes = known
    api_key.save(update_fields=['scopes', 'updated_at'])
    record_api_key_audit(
        organization=api_key.organization,
        api_key=api_key,
        actor=actor,
        action=OrgApiKeyAudit.ACTION_CHANGE,
        scopes_before=scopes_before,
        scopes_after=known,
    )
    return api_key


def record_api_key_audit(
    *,
    organization,
    api_key,
    actor,
    action,
    scopes_before=None,
    scopes_after=None,
):
    return OrgApiKeyAudit.objects.create(
        organization=organization,
        api_key=api_key,
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        action=action,
        key_prefix=getattr(api_key, 'prefix', '') or '',
        scopes_before=list(scopes_before or []),
        scopes_after=list(scopes_after or []),
    )


def authenticate_api_key(raw_key: str):
    """
    Resolve a raw key to an active OrgApiKey, or None.

    Revoked / inactive keys return None so callers can raise 401.
    Always hits the DB (no cache) so revoke is immediate.
    """
    prefix = parse_key_prefix(raw_key)
    if prefix is None:
        return None

    try:
        api_key = (
            OrgApiKey.objects.select_related('organization')
            .get(prefix=prefix)
        )
    except OrgApiKey.DoesNotExist:
        return None

    if not verify_raw_key(raw_key, api_key.key_hash):
        return None
    if not api_key.is_active:
        return None
    if not api_key.organization.is_active:
        return None
    return api_key


def touch_api_key_last_used(api_key):
    OrgApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())


def api_key_has_scope(api_key, scope_code: str) -> bool:
    if api_key is None:
        return False
    if scope_code not in ALL_API_SCOPE_CODES:
        return False
    return scope_code in (api_key.scopes or [])
