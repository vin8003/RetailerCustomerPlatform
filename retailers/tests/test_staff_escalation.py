"""OE-98 review fixes: callers cannot grant what they do not hold."""
import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.models import OrgRole, OrgStaffMembership
from retailers.tests.test_staff_roles import _make_retailer


def _role(org, slug, perms):
    return OrgRole.objects.create(
        organization=org, name=slug.title(), slug=slug, permissions=perms
    )


def _staff(org, username, role):
    user = User.objects.create_user(
        username=username, email=f"{username}@t.com", password="TestPass123!",
        user_type="retailer", is_active=True,
    )
    OrgStaffMembership.objects.create(organization=org, user=user, role=role)
    return user


@pytest.mark.django_db
class TestEscalation:
    def _setup(self, perms):
        owner, profile = _make_retailer("esc_owner", "Esc Shop")
        org = profile.organization
        role = _role(org, "mgr", perms)
        mgr = _staff(org, "esc_mgr", role)
        return owner, org, role, mgr

    def test_roles_manage_cannot_add_permissions_it_lacks(self, api_client):
        _owner, org, role, mgr = self._setup(["roles.manage"])
        other = _role(org, "other", [])
        api_client.force_authenticate(user=mgr)
        resp = api_client.patch(
            reverse("organization_role_detail", kwargs={"org_id": org.id, "role_id": other.id}),
            {"permissions": ["staff.manage"]}, format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        other.refresh_from_db()
        assert other.permissions == []

    def test_roles_manage_cannot_edit_own_role(self, api_client):
        _owner, org, role, mgr = self._setup(["roles.manage"])
        api_client.force_authenticate(user=mgr)
        resp = api_client.patch(
            reverse("organization_role_detail", kwargs={"org_id": org.id, "role_id": role.id}),
            {"permissions": ["roles.manage", "org.update"]}, format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_role_create_limited_to_held_permissions(self, api_client):
        _owner, org, _role_obj, mgr = self._setup(["roles.manage"])
        api_client.force_authenticate(user=mgr)
        url = reverse("organization_roles", kwargs={"org_id": org.id})
        bad = api_client.post(url, {"name": "X", "slug": "x", "permissions": ["org.update"]}, format="json")
        ok = api_client.post(url, {"name": "Y", "slug": "y", "permissions": ["roles.manage"]}, format="json")
        assert bad.status_code == status.HTTP_403_FORBIDDEN
        assert ok.status_code == status.HTTP_201_CREATED

    def test_staff_manage_cannot_self_promote_or_assign_admin(self, api_client):
        _owner, org, role, mgr = self._setup(["staff.manage"])
        admin_role = OrgRole.objects.get(organization=org, slug="admin")
        membership = OrgStaffMembership.objects.get(organization=org, user=mgr)
        api_client.force_authenticate(user=mgr)
        self_edit = api_client.patch(
            reverse("organization_staff_detail", kwargs={"org_id": org.id, "membership_id": membership.id}),
            {"role_id": admin_role.id}, format="json",
        )
        assert self_edit.status_code == status.HTTP_403_FORBIDDEN
        assign = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {"username": "newbie", "password": "Str0ng!pass-123", "role_id": admin_role.id},
            format="json",
        )
        assert assign.status_code == status.HTTP_403_FORBIDDEN

    def test_staff_manage_cannot_demote_higher_privilege_member(self, api_client):
        owner, org, role, mgr = self._setup(["staff.manage"])
        owner_membership = OrgStaffMembership.objects.get(organization=org, user=owner)
        cashier = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=mgr)
        resp = api_client.patch(
            reverse("organization_staff_detail", kwargs={"org_id": org.id, "membership_id": owner_membership.id}),
            {"role_id": cashier.id}, format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_attach_user_id_refusals_are_indistinguishable(self, api_client):
        owner, org, role, mgr = self._setup(["staff.manage"])
        other_owner, _p = _make_retailer("esc_other", "Other Shop")
        cashier = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=owner)
        url = reverse("organization_staff", kwargs={"org_id": org.id})
        missing = api_client.post(url, {"user_id": 999999, "role_id": cashier.id}, format="json")
        foreign = api_client.post(url, {"user_id": other_owner.id, "role_id": cashier.id}, format="json")
        assert missing.status_code == foreign.status_code == status.HTTP_400_BAD_REQUEST
        assert missing.data == foreign.data

    def test_weak_password_rejected(self, api_client):
        owner, org, _r, _m = self._setup([])
        cashier = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {"username": "weak1", "password": "1234", "role_id": cashier.id}, format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "password" in resp.data

    def test_member_without_staff_manage_sees_only_self(self, api_client):
        owner, org, role, mgr = self._setup(["roles.manage"])
        api_client.force_authenticate(user=mgr)
        resp = api_client.get(reverse("organization_staff", kwargs={"org_id": org.id}))
        assert resp.status_code == status.HTTP_200_OK
        rows = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
        assert [r["user"] for r in rows] == [mgr.id]

    def test_owner_still_unrestricted(self, api_client):
        owner, org, _r, _m = self._setup([])
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("organization_roles", kwargs={"org_id": org.id}),
            {"name": "All", "slug": "all", "permissions": ["org.update", "staff.manage"]}, format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
