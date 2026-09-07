"""
OE-101 / F-0004 — Shop module flags.

Covers: catalog/versioned flags read API, modules.manage gate, disable → 403
stable error_code, enable + permitted role → allowed, audit on change,
cross-tenant isolation, auth matrix.
"""
import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.models import OrgAuditLog, OrgModuleFlags, OrgRole, RetailerProfile
from retailers.module_flags_catalog import (
    ALL_MODULE_CODES,
    ERROR_CODE_MODULE_DISABLED,
    MODULE_CATALOG_VERSION,
)
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import PERMISSION_CATALOG_VERSION


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


def _module_flags_url(org_id):
    return reverse("organization_module_flags", kwargs={"org_id": org_id})


def _module_catalog_url(org_id):
    return reverse("organization_module_flags_catalog", kwargs={"org_id": org_id})


@pytest.mark.django_db
class TestModuleFlagsCatalogAndBootstrap:
    def test_fresh_org_bootstraps_all_modules_enabled(self):
        user, profile = _make_retailer("mod_boot_owner", "Mod Boot Shop", with_org=False)
        org = ensure_organization_for_profile(profile, name="Mod Boot Org")
        row = OrgModuleFlags.objects.get(organization=org)
        assert set(row.flags.keys()) == set(ALL_MODULE_CODES)
        assert all(row.flags[code] is True for code in ALL_MODULE_CODES)

    def test_module_catalog_endpoint_versioned(self, api_client):
        owner, profile = _make_retailer("mod_cat_owner", "Mod Cat Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.get(_module_catalog_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == MODULE_CATALOG_VERSION
        codes = {m["code"] for m in resp.data["modules"]}
        assert codes == set(ALL_MODULE_CODES)

    def test_modules_manage_in_permission_catalog(self, api_client):
        owner, profile = _make_retailer("mod_perm_owner", "Mod Perm Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.get(
            reverse("organization_permission_catalog", kwargs={"org_id": org.id})
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == PERMISSION_CATALOG_VERSION
        codes = {p["code"] for p in resp.data["permissions"]}
        assert "modules.manage" in codes


@pytest.mark.django_db
class TestModuleFlagsReadWrite:
    def test_same_tenant_can_read_flags_for_nav(self, api_client):
        owner, profile = _make_retailer("mod_read_owner", "Mod Read Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.get(_module_flags_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["organization_id"] == org.id
        assert set(resp.data["flags"].keys()) == set(ALL_MODULE_CODES)

    def test_cashier_can_read_flags_without_modules_manage(self, api_client):
        owner, profile = _make_retailer("mod_cash_owner", "Mod Cash Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=owner)
        api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": "mod_cashier",
                "password": "CashPass123!",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        cashier = User.objects.get(username="mod_cashier")
        api_client.force_authenticate(user=cashier)
        resp = api_client.get(_module_flags_url(org.id))
        assert resp.status_code == status.HTTP_200_OK

    def test_cashier_cannot_patch_flags_returns_403_unchanged(self, api_client):
        owner, profile = _make_retailer("mod_patch_denied", "Mod Patch Denied")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=owner)
        api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": "mod_patch_cashier",
                "password": "CashPass123!",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        before = OrgModuleFlags.objects.get(organization=org).flags.copy()
        cashier = User.objects.get(username="mod_patch_cashier")
        api_client.force_authenticate(user=cashier)
        resp = api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"catalog": False}},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        after = OrgModuleFlags.objects.get(organization=org).flags
        assert after == before

    def test_owner_patch_disables_module_and_writes_audit(self, api_client):
        owner, profile = _make_retailer("mod_audit_owner", "Mod Audit Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"catalog": False, "orders": False}},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["flags"]["catalog"] is False
        assert resp.data["flags"]["orders"] is False
        assert resp.data["flags"]["customers"] is True

        row = OrgAuditLog.objects.get(
            organization=org,
            object_type=OrgAuditLog.OBJECT_MODULE_FLAGS,
            object_id=str(org.id),
        )
        assert row.action == OrgAuditLog.ACTION_UPDATE
        assert row.actor_id == owner.id
        assert row.summary_before["catalog"] is True
        assert row.summary_after["catalog"] is False

    def test_partial_patch_preserves_other_disabled_flags(self, api_client):
        owner, profile = _make_retailer("mod_partial", "Mod Partial Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)

        first = api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"catalog": False}},
            format="json",
        )
        assert first.status_code == status.HTTP_200_OK
        assert first.data["flags"]["catalog"] is False

        second = api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"orders": False}},
            format="json",
        )
        assert second.status_code == status.HTTP_200_OK
        assert second.data["flags"]["catalog"] is False
        assert second.data["flags"]["orders"] is False
        assert second.data["flags"]["customers"] is True
        assert second.data["flags"]["rewards"] is True

        stored = OrgModuleFlags.objects.get(organization=org).flags
        assert stored["catalog"] is False
        assert stored["orders"] is False


@pytest.mark.django_db
class TestModuleEnforcement:
    def test_disabled_catalog_returns_403_stable_error_code(self, api_client):
        owner, profile = _make_retailer("mod_off_cat", "Mod Off Cat")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"catalog": False}},
            format="json",
        )
        resp = api_client.get(reverse("get_retailer_products"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
        assert resp.data["module"] == "catalog"

    def test_enabled_catalog_allowed_for_permitted_retailer(self, api_client):
        owner, _profile = _make_retailer("mod_on_cat", "Mod On Cat")
        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse("get_retailer_products"))
        assert resp.status_code == status.HTTP_200_OK

    def test_disabled_orders_blocks_order_stats(self, api_client):
        owner, profile = _make_retailer("mod_off_ord", "Mod Off Ord")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"orders": False}},
            format="json",
        )
        resp = api_client.get(reverse("get_order_stats"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
        assert resp.data["module"] == "orders"

    def test_disabled_customers_blocks_crm_list(self, api_client):
        owner, profile = _make_retailer("mod_off_crm", "Mod Off CRM")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"customers": False}},
            format="json",
        )
        resp = api_client.get(reverse("get_retailer_customers"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
        assert resp.data["module"] == "customers"

    def test_disabled_rewards_blocks_reward_config(self, api_client):
        owner, profile = _make_retailer("mod_off_rew", "Mod Off Rew")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"rewards": False}},
            format="json",
        )
        resp = api_client.get(reverse("manage_reward_configuration"))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["error_code"] == ERROR_CODE_MODULE_DISABLED
        assert resp.data["module"] == "rewards"

    def test_reenabled_module_restores_api_access(self, api_client):
        owner, profile = _make_retailer("mod_reenable", "Mod Reenable")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"catalog": False}},
            format="json",
        )
        blocked = api_client.get(reverse("get_retailer_products"))
        assert blocked.status_code == status.HTTP_403_FORBIDDEN
        assert blocked.data["error_code"] == ERROR_CODE_MODULE_DISABLED

        api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"catalog": True}},
            format="json",
        )
        allowed = api_client.get(reverse("get_retailer_products"))
        assert allowed.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestModuleFlagsCrossTenant:
    def test_cross_tenant_read_forbidden(self, api_client):
        owner_a, profile_a = _make_retailer("mod_tenant_a", "Mod Tenant A")
        _owner_b, profile_b = _make_retailer("mod_tenant_b", "Mod Tenant B")
        org_b = profile_b.organization
        api_client.force_authenticate(user=owner_a)
        resp = api_client.get(_module_flags_url(org_b.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "not found or access denied" in resp.data["error"].lower()

    def test_cross_tenant_patch_forbidden_and_unchanged(self, api_client):
        owner_a, _profile_a = _make_retailer("mod_xpatch_a", "Mod XPatch A")
        _owner_b, profile_b = _make_retailer("mod_xpatch_b", "Mod XPatch B")
        org_b = profile_b.organization
        before = OrgModuleFlags.objects.get(organization=org_b).flags.copy()
        api_client.force_authenticate(user=owner_a)
        resp = api_client.patch(
            _module_flags_url(org_b.id),
            {"flags": {"catalog": False}},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        after = OrgModuleFlags.objects.get(organization=org_b).flags
        assert after == before


@pytest.mark.django_db
class TestModuleFlagsQueryBudget:
    """Hot module-flags endpoints must stay bounded (no N+1, tenant-scoped)."""

    def test_module_flags_get_query_count(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("mod_q_get", "Mod Query Get")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(2):
            resp = api_client.get(_module_flags_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert set(resp.data["flags"].keys()) == set(ALL_MODULE_CODES)

    def test_module_flags_patch_query_count(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("mod_q_patch", "Mod Query Patch")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(4):
            resp = api_client.patch(
                _module_flags_url(org.id),
                {"flags": {"catalog": False}},
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["flags"]["catalog"] is False

    def test_module_flags_catalog_query_count(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("mod_q_cat", "Mod Query Cat")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(1):
            resp = api_client.get(_module_catalog_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == MODULE_CATALOG_VERSION

    def test_cross_tenant_module_flags_get_denied_one_query(
        self, api_client, django_assert_num_queries
    ):
        owner_a, profile_a = _make_retailer("mod_iso_get_a", "Mod Iso Get A")
        owner_b, _profile_b = _make_retailer("mod_iso_get_b", "Mod Iso Get B")
        api_client.force_authenticate(user=owner_b)
        with django_assert_num_queries(1):
            resp = api_client.get(_module_flags_url(profile_a.organization_id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_module_flags_patch_denied_one_query(
        self, api_client, django_assert_num_queries
    ):
        owner_a, profile_a = _make_retailer("mod_iso_patch_a", "Mod Iso Patch A")
        owner_b, _profile_b = _make_retailer("mod_iso_patch_b", "Mod Iso Patch B")
        api_client.force_authenticate(user=owner_b)
        with django_assert_num_queries(1):
            resp = api_client.patch(
                _module_flags_url(profile_a.organization_id),
                {"flags": {"catalog": False}},
                format="json",
            )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestModuleFlagsAuthMatrix:
    def test_unauthenticated_get_returns_401(self, api_client):
        owner, profile = _make_retailer("mod_unauth", "Mod Unauth")
        org = profile.organization
        resp = api_client.get(_module_flags_url(org.id))
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unknown_module_code_on_patch_returns_400(self, api_client):
        owner, profile = _make_retailer("mod_bad_code", "Mod Bad Code")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            _module_flags_url(org.id),
            {"flags": {"not_a_module": False}},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_flags_patch_returns_400_unchanged(self, api_client):
        owner, profile = _make_retailer("mod_empty", "Mod Empty")
        org = profile.organization
        before = OrgModuleFlags.objects.get(organization=org).flags.copy()
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            _module_flags_url(org.id),
            {"flags": {}},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        after = OrgModuleFlags.objects.get(organization=org).flags
        assert after == before
