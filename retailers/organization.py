"""
Organization (tenant) helpers for OE-97 / F-0001 and OE-98 / F-0002.

Location stays implicit for existing single-shop tenants: RetailerProfile
remains the operational shop record; Organization is the tenant parent.

Staff RBAC (OE-98): named OrgRole + OrgStaffMembership bound to AUTH_USER_MODEL.
Permission checks read membership on every request (role changes take effect
on the next authorized call). Org owner remains implicit admin.
"""
from django.db import transaction

from .models import (
    Organization,
    OrgRole,
    OrgStaffMembership,
    OrgStaffRoleAudit,
    RetailerProfile,
)
from .permissions_catalog import (
    ALL_PERMISSION_CODES,
    BOOTSTRAP_ROLES,
    ROLE_SLUG_ADMIN,
)


def ensure_organization_for_profile(profile, *, name=None):
    """
    Create and attach an Organization if the shop has none.

    Idempotent. Uses the shop name when ``name`` is omitted.
    Bootstraps Admin/Cashier roles and owner Admin membership (OE-98).
    """
    if profile.organization_id:
        org = profile.organization
        ensure_org_rbac_bootstrap(org)
        return org

    org_name = (name or '').strip() or profile.shop_name or (
        f"{profile.user.get_username()}'s Organization"
    )

    with transaction.atomic():
        locked = (
            RetailerProfile.objects.select_for_update()
            .select_related('organization', 'user')
            .get(pk=profile.pk)
        )
        if locked.organization_id:
            profile.organization = locked.organization
            ensure_org_rbac_bootstrap(locked.organization)
            return locked.organization

        org = Organization.objects.create(
            name=org_name,
            owner=locked.user,
            is_active=True,
        )
        locked.organization = org
        locked.save(update_fields=['organization', 'updated_at'])
        profile.organization = org
        ensure_org_rbac_bootstrap(org)
        return org


def ensure_org_rbac_bootstrap(organization):
    """
    Ensure system roles exist and the org owner has Admin membership.

    A fresh org has exactly one owner with all permissions (S-0002A).
    Idempotent for existing orgs created before OE-98.
    """
    if organization is None:
        return

    with transaction.atomic():
        org = (
            Organization.objects.select_for_update()
            .select_related('owner')
            .get(pk=organization.pk)
        )
        roles_by_slug = {}
        for spec in BOOTSTRAP_ROLES:
            role, _created = OrgRole.objects.get_or_create(
                organization=org,
                slug=spec['slug'],
                defaults={
                    'name': spec['name'],
                    'permissions': list(spec['permissions']),
                    'is_system': spec['is_system'],
                },
            )
            # Keep system admin permissions complete if catalog grows
            if role.slug == ROLE_SLUG_ADMIN:
                desired = sorted(ALL_PERMISSION_CODES)
                if sorted(role.permissions or []) != desired:
                    role.permissions = desired
                    role.save(update_fields=['permissions', 'updated_at'])
            roles_by_slug[role.slug] = role

        admin_role = roles_by_slug[ROLE_SLUG_ADMIN]
        membership, created = OrgStaffMembership.objects.get_or_create(
            organization=org,
            user_id=org.owner_id,
            defaults={
                'role': admin_role,
                'is_active': True,
            },
        )
        if not created:
            updates = []
            if membership.role_id != admin_role.id:
                membership.role = admin_role
                updates.append('role')
            if not membership.is_active:
                membership.is_active = True
                updates.append('is_active')
            if updates:
                updates.append('updated_at')
                membership.save(update_fields=updates)


def get_organization_for_user(user):
    """
    Resolve the caller's organization via RetailerProfile or staff membership.

    Returns None when the user has no shop profile and no active staff seat.
    """
    try:
        profile = (
            RetailerProfile.objects.select_related('organization')
            .get(user=user)
        )
    except RetailerProfile.DoesNotExist:
        profile = None

    if profile is not None:
        if profile.organization_id:
            return profile.organization
        return ensure_organization_for_profile(profile)

    membership = (
        OrgStaffMembership.objects.select_related('organization')
        .filter(user=user, is_active=True)
        .order_by('id')
        .first()
    )
    if membership is None:
        return None
    return membership.organization


def get_active_staff_membership(user, organization):
    """Return active OrgStaffMembership for user in org, or None."""
    if not user or organization is None:
        return None
    return (
        OrgStaffMembership.objects.select_related('role')
        .filter(
            organization=organization,
            user=user,
            is_active=True,
        )
        .first()
    )


def user_permission_codes(user, organization):
    """
    Permission codes effective for this user in the org.

    Owner always receives the full catalog (implicit admin).
    Otherwise codes come from the active membership role (read live from DB).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return frozenset()
    if organization is None:
        return frozenset()
    if organization.owner_id == user.id:
        return frozenset(ALL_PERMISSION_CODES)

    membership = get_active_staff_membership(user, organization)
    if membership is None:
        return frozenset()
    codes = membership.role.permissions or []
    return frozenset(c for c in codes if c in ALL_PERMISSION_CODES)


def user_has_org_permission(user, organization, permission_code):
    """True when the user may perform ``permission_code`` in this org."""
    return permission_code in user_permission_codes(user, organization)


def user_is_org_staff_admin(user, organization):
    """
    Staff-admin gate for org APIs.

    OE-98: owner or any member with ``staff.manage`` (Admin role by default).
    """
    return user_has_org_permission(user, organization, 'staff.manage')


def is_org_owner(user, organization):
    return bool(
        user
        and organization is not None
        and organization.owner_id == getattr(user, 'id', None)
    )


def would_remove_last_owner(organization, *, target_user, new_role=None, deactivate=False):
    """
    True when the mutation would strip the org owner's admin seat.

    S-0002A: removing the last owner is forbidden. Owner stays on
    Organization.owner; staff APIs must not revoke or demote that user.
    """
    if organization is None or target_user is None:
        return False
    if target_user.id != organization.owner_id:
        return False
    if deactivate:
        return True
    if new_role is not None:
        perms = set(new_role.permissions or [])
        if not ALL_PERMISSION_CODES.issubset(perms):
            return True
    return False


def record_staff_role_audit(
    *,
    organization,
    actor,
    target_user,
    action,
    from_role=None,
    to_role=None,
):
    return OrgStaffRoleAudit.objects.create(
        organization=organization,
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        target_user=target_user,
        action=action,
        from_role=from_role,
        to_role=to_role,
    )


def organization_is_session_blocked(user):
    """
    True when the user's tenant is disabled and must not get new sessions.
    """
    org = None
    try:
        profile = (
            RetailerProfile.objects.select_related('organization')
            .get(user=user)
        )
        org = profile.organization
    except RetailerProfile.DoesNotExist:
        membership = (
            OrgStaffMembership.objects.select_related('organization')
            .filter(user=user, is_active=True)
            .first()
        )
        if membership is not None:
            org = membership.organization

    if org is None:
        return False
    return not org.is_active


def user_belongs_to_organization(user, organization):
    """Same-tenant check: owner, location profile, or active staff membership."""
    if not user or organization is None:
        return False
    if organization.owner_id == user.id:
        return True
    if RetailerProfile.objects.filter(
        user=user, organization=organization
    ).exists():
        return True
    return OrgStaffMembership.objects.filter(
        organization=organization,
        user=user,
        is_active=True,
    ).exists()
