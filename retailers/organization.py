"""
Organization (tenant) helpers for OE-97 / F-0001.

Location stays implicit for existing single-shop tenants: RetailerProfile
remains the operational shop record; Organization is the tenant parent.
"""
from django.db import transaction

from .models import Organization, RetailerProfile


def ensure_organization_for_profile(profile, *, name=None):
    """
    Create and attach an Organization if the shop has none.

    Idempotent. Uses the shop name when ``name`` is omitted.
    """
    if profile.organization_id:
        return profile.organization

    org_name = (name or '').strip() or profile.shop_name or (
        f"{profile.user.get_username()}'s Organization"
    )

    with transaction.atomic():
        # Do not select_related('organization') here: Postgres rejects
        # FOR UPDATE on the nullable side of an OUTER JOIN.
        locked = (
            RetailerProfile.objects.select_for_update()
            .select_related('user')
            .get(pk=profile.pk)
        )
        if locked.organization_id:
            # Fresh fetch of the related org (not locked via OUTER JOIN).
            org = Organization.objects.get(pk=locked.organization_id)
            profile.organization = org
            return org

        org = Organization.objects.create(
            name=org_name,
            owner=locked.user,
            is_active=True,
        )
        locked.organization = org
        locked.save(update_fields=['organization', 'updated_at'])
        profile.organization = org
        return org


def get_organization_for_user(user):
    """
    Resolve the caller's organization via their RetailerProfile.

    Returns None when the user has no shop profile.
    """
    try:
        profile = (
            RetailerProfile.objects.select_related('organization')
            .get(user=user)
        )
    except RetailerProfile.DoesNotExist:
        return None
    if profile.organization_id:
        return profile.organization
    return ensure_organization_for_profile(profile)


def user_is_org_staff_admin(user, organization):
    """
    Staff-admin gate for org APIs.

    Until OE-98 RBAC, the org owner is the only staff-admin.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if organization is None:
        return False
    return organization.owner_id == user.id


def organization_is_session_blocked(user):
    """
    True when the user's tenant is disabled and must not get new sessions.
    """
    try:
        profile = (
            RetailerProfile.objects.select_related('organization')
            .get(user=user)
        )
    except RetailerProfile.DoesNotExist:
        return False
    org = profile.organization
    if org is None:
        return False
    return not org.is_active
