"""
Unified immutable shop audit log (OE-99 / F-0003).

Sensitive mutations call ``record_org_audit_event`` to append rows. Read access
is gated by ``audit.read`` (F-0002 RBAC).
"""
from .models import OrgAuditLog


def record_org_audit_event(
    *,
    organization,
    actor,
    action,
    object_type,
    object_id,
    summary_before=None,
    summary_after=None,
    location=None,
):
    """
    Append an immutable audit row. Returns the created OrgAuditLog instance.
    """
    return OrgAuditLog.objects.create(
        organization=organization,
        location=location,
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        summary_before=dict(summary_before or {}),
        summary_after=dict(summary_after or {}),
    )


def staff_role_audit_summaries(*, target_user, from_role=None, to_role=None):
    """Build before/after summaries for staff membership mutations."""
    before = {}
    after = {}
    if target_user is not None:
        before['user_id'] = target_user.id
        before['username'] = target_user.get_username()
        after['user_id'] = target_user.id
        after['username'] = target_user.get_username()
    if from_role is not None:
        before['role_id'] = from_role.id
        before['role_slug'] = from_role.slug
    if to_role is not None:
        after['role_id'] = to_role.id
        after['role_slug'] = to_role.slug
    return before, after


def api_key_audit_summaries(*, api_key, scopes_before=None, scopes_after=None):
    """Build before/after summaries for API key mutations."""
    prefix = getattr(api_key, 'prefix', '') or ''
    name = getattr(api_key, 'name', '') or ''
    before = {
        'api_key_id': api_key.id,
        'prefix': prefix,
        'name': name,
        'scopes': list(scopes_before or []),
    }
    after = {
        'api_key_id': api_key.id,
        'prefix': prefix,
        'name': name,
        'scopes': list(scopes_after or []),
    }
    return before, after
