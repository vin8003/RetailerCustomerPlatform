"""
OE-98 / F-0002 — Shop staff roles.

Covers: permission catalog, owner bootstrap, assign named role, cashier 403,
role change takes effect next request, unauthorized cannot change roles,
cross-tenant isolation, audit rows.
"""
import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.models import (
    OrgRole,
    OrgStaffMembership,
    OrgStaffRoleAudit,
    RetailerProfile,
)
from retailers.organization import (
    ensure_organization_for_profile,
    user_has_org_permission,
    user_is_org_staff_admin,
)
from retailers.permissions_catalog import (
    ALL_PERMISSION_CODES,
    PERMISSION_CATALOG_VERSION,
    ROLE_SLUG_ADMIN,
    ROLE_SLUG_CASHIER,
    validate_permission_codes,
)


def _make_retailer(username, shop_name, *, with_org=True):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    profile = RetailerProfile.objects.create(
        user=user,
        shop_name=shop_name,
        address_line1="1 Main",
        city="City",
        state="State",
        pincode="110001",
        is_active=True,
    )
    if with_org:
        ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


@pytest.mark.django_db
class TestPermissionCatalogAndBootstrap:
    def test_unknown_permission_codes_rejected(self):
        known, unknown = validate_permission_codes(
            ['org.update', 'not.a.real.perm', 'staff.manage']
        )
        assert known == ['org.update', 'staff.manage']
        assert unknown == ['not.a.real.perm']

    def test_fresh_org_has_one_owner_with_all_permissions(self, api_client):
        user, profile = _make_retailer("boot_owner", "Boot Shop", with_org=False)
        org = ensure_organization_for_profile(profile, name="Boot Org")

        assert org.owner_id == user.id
        assert user_has_org_permission(user, org, 'org.update')
        assert user_has_org_permission(user, org, 'staff.manage')
        assert user_has_org_permission(user, org, 'roles.manage')
        assert user_is_org_staff_admin(user, org)

        roles = {r.slug: r for r in OrgRole.objects.filter(organization=org)}
        assert set(roles) == {ROLE_SLUG_ADMIN, ROLE_SLUG_CASHIER}
        assert set(roles[ROLE_SLUG_ADMIN].permissions) == set(ALL_PERMISSION_CODES)
        assert roles[ROLE_SLUG_CASHIER].permissions == []

        memberships = list(
            OrgStaffMembership.objects.filter(organization=org, is_active=True)
        )
        assert len(memberships) == 1
        assert memberships[0].user_id == user.id
        assert memberships[0].role.slug == ROLE_SLUG_ADMIN

    def test_catalog_endpoint_versioned(self, api_client):
        user, profile = _make_retailer("cat_owner", "Cat Shop")
        org = profile.organization
        api_client.force_authenticate(user=user)
        resp = api_client.get(
            reverse("organization_permission_catalog", kwargs={"org_id": org.id})
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == PERMISSION_CATALOG_VERSION
        codes = {p["code"] for p in resp.data["permissions"]}
        assert codes == set(ALL_PERMISSION_CODES)


@pytest.mark.django_db
class TestStaffRoleAssignment:
    def test_admin_assigns_staff_to_named_cashier_role(self, api_client):
        owner, profile = _make_retailer("assign_owner", "Assign Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": "cashier_one",
                "password": "CashPass123!",
                "email": "cashier_one@test.com",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["role_slug"] == ROLE_SLUG_CASHIER
        assert resp.data["username"] == "cashier_one"
        assert resp.data["permissions"] == []

        staff_user = User.objects.get(username="cashier_one")
        assert staff_user.user_type == "retailer"
        assert OrgStaffMembership.objects.filter(
            organization=org, user=staff_user, role=cashier_role, is_active=True
        ).exists()
        assert OrgStaffRoleAudit.objects.filter(
            organization=org,
            target_user=staff_user,
            action=OrgStaffRoleAudit.ACTION_GRANT,
        ).exists()

    def test_unknown_permission_on_role_save_rejected(self, api_client):
        owner, profile = _make_retailer("badperm_owner", "BadPerm Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("organization_roles", kwargs={"org_id": org.id}),
            {
                "name": "Supervisor",
                "slug": "supervisor",
                "permissions": ["org.update", "invented.perm"],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert not OrgRole.objects.filter(organization=org, slug="supervisor").exists()

    def test_cannot_remove_last_owner(self, api_client):
        owner, profile = _make_retailer("last_owner", "Last Owner Shop")
        org = profile.organization
        membership = OrgStaffMembership.objects.get(
            organization=org, user=owner, is_active=True
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.delete(
            reverse(
                "organization_staff_detail",
                kwargs={"org_id": org.id, "membership_id": membership.id},
            )
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        membership.refresh_from_db()
        assert membership.is_active is True


@pytest.mark.django_db
class TestCashierForbiddenMatrix:
    def _owner_and_cashier(self, api_client, prefix):
        owner, profile = _make_retailer(f"{prefix}_owner", f"{prefix} Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": f"{prefix}_cashier",
                "password": "CashPass123!",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED
        cashier = User.objects.get(username=f"{prefix}_cashier")
        return owner, org, cashier, created.data["id"]

    def test_cashier_cannot_patch_org_returns_403_unchanged(self, api_client):
        _owner, org, cashier, _mid = self._owner_and_cashier(api_client, "c403")
        original_name = org.name

        api_client.force_authenticate(user=cashier)
        # Cashier can read same-tenant org
        get_resp = api_client.get(
            reverse("organization_detail", kwargs={"org_id": org.id})
        )
        assert get_resp.status_code == status.HTTP_200_OK

        patch = api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org.id}),
            {"name": "Hijacked", "is_active": False},
            format="json",
        )
        assert patch.status_code == status.HTTP_403_FORBIDDEN
        org.refresh_from_db()
        assert org.name == original_name
        assert org.is_active is True
        assert not user_has_org_permission(cashier, org, "org.update")

    def test_cashier_cannot_change_another_users_role(self, api_client):
        owner, org, cashier, cashier_mid = self._owner_and_cashier(api_client, "nochg")
        owner_membership = OrgStaffMembership.objects.get(
            organization=org, user=owner
        )
        admin_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_ADMIN)

        api_client.force_authenticate(user=cashier)
        # Try to promote self
        self_patch = api_client.patch(
            reverse(
                "organization_staff_detail",
                kwargs={"org_id": org.id, "membership_id": cashier_mid},
            ),
            {"role_id": admin_role.id},
            format="json",
        )
        assert self_patch.status_code == status.HTTP_403_FORBIDDEN
        mid = OrgStaffMembership.objects.get(pk=cashier_mid)
        assert mid.role.slug == ROLE_SLUG_CASHIER

        # Try to demote owner
        owner_patch = api_client.patch(
            reverse(
                "organization_staff_detail",
                kwargs={"org_id": org.id, "membership_id": owner_membership.id},
            ),
            {"role_id": OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER).id},
            format="json",
        )
        assert owner_patch.status_code == status.HTTP_403_FORBIDDEN
        owner_membership.refresh_from_db()
        assert owner_membership.role.slug == ROLE_SLUG_ADMIN


@pytest.mark.django_db
class TestRoleChangeTakesEffectNextRequest:
    def test_promote_cashier_then_patch_succeeds(self, api_client):
        owner, profile = _make_retailer("promo_owner", "Promo Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        admin_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_ADMIN)

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": "promo_cashier",
                "password": "CashPass123!",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED
        membership_id = created.data["id"]
        cashier = User.objects.get(username="promo_cashier")

        api_client.force_authenticate(user=cashier)
        denied = api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org.id}),
            {"name": "Should Fail"},
            format="json",
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        # Admin changes role; next cashier request must see new perms (live DB read)
        api_client.force_authenticate(user=owner)
        changed = api_client.patch(
            reverse(
                "organization_staff_detail",
                kwargs={"org_id": org.id, "membership_id": membership_id},
            ),
            {"role_id": admin_role.id},
            format="json",
        )
        assert changed.status_code == status.HTTP_200_OK
        assert changed.data["role_slug"] == ROLE_SLUG_ADMIN
        assert OrgStaffRoleAudit.objects.filter(
            organization=org,
            target_user=cashier,
            action=OrgStaffRoleAudit.ACTION_CHANGE,
        ).exists()

        api_client.force_authenticate(user=cashier)
        assert user_has_org_permission(cashier, org, "org.update")
        allowed = api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org.id}),
            {"name": "Promoted Name"},
            format="json",
        )
        assert allowed.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.name == "Promoted Name"


@pytest.mark.django_db
class TestStaffCrossTenantIsolation:
    def test_tenant_a_cannot_read_or_mutate_tenant_b_staff(self, api_client):
        owner_a, profile_a = _make_retailer("ten_a", "Tenant A")
        owner_b, profile_b = _make_retailer("ten_b", "Tenant B")
        org_a = profile_a.organization
        org_b = profile_b.organization

        cashier_b = OrgRole.objects.get(organization=org_b, slug=ROLE_SLUG_CASHIER)
        api_client.force_authenticate(user=owner_b)
        created = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org_b.id}),
            {
                "username": "ten_b_cashier",
                "password": "CashPass123!",
                "role_id": cashier_b.id,
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED
        membership_b_id = created.data["id"]
        before_role = OrgStaffMembership.objects.get(pk=membership_b_id).role_id

        api_client.force_authenticate(user=owner_a)
        # List B staff
        listed = api_client.get(
            reverse("organization_staff", kwargs={"org_id": org_b.id})
        )
        assert listed.status_code == status.HTTP_403_FORBIDDEN

        # Read B roles
        roles = api_client.get(
            reverse("organization_roles", kwargs={"org_id": org_b.id})
        )
        assert roles.status_code == status.HTTP_403_FORBIDDEN

        # Mutate B membership
        admin_a = OrgRole.objects.get(organization=org_a, slug=ROLE_SLUG_ADMIN)
        mutated = api_client.patch(
            reverse(
                "organization_staff_detail",
                kwargs={"org_id": org_b.id, "membership_id": membership_b_id},
            ),
            {"role_id": admin_a.id},
            format="json",
        )
        assert mutated.status_code == status.HTTP_403_FORBIDDEN
        mid = OrgStaffMembership.objects.get(pk=membership_b_id)
        assert mid.role_id == before_role

    def test_unauthenticated_staff_endpoints_401(self, api_client, retailer):
        org_id = retailer.organization_id
        assert (
            api_client.get(
                reverse("organization_staff", kwargs={"org_id": org_id})
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )
        assert (
            api_client.post(
                reverse("organization_staff", kwargs={"org_id": org_id}),
                {},
                format="json",
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )
        assert (
            api_client.get(
                reverse("organization_roles", kwargs={"org_id": org_id})
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )
