"""
OE-99 / F-0003 — Immutable shop audit log.

Covers: write-on-mutation, audit.read permission gate, append-only read API,
cross-tenant isolation, HO location filter.
"""
import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.audit_log import record_org_audit_event
from retailers.models import OrgAuditLog, OrgRole, RetailerProfile
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import (
    ALL_PERMISSION_CODES,
    PERMISSION_CATALOG_VERSION,
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


def _audit_url(org_id):
    return reverse("organization_audit_log", kwargs={"org_id": org_id})


@pytest.mark.django_db
class TestAuditLogCatalog:
    def test_audit_read_in_permission_catalog(self, api_client):
        owner, profile = _make_retailer("audit_cat_owner", "Audit Cat Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.get(
            reverse("organization_permission_catalog", kwargs={"org_id": org.id})
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == PERMISSION_CATALOG_VERSION
        codes = {p["code"] for p in resp.data["permissions"]}
        assert "audit.read" in codes
        assert codes == set(ALL_PERMISSION_CODES)


@pytest.mark.django_db
class TestAuditLogWriteOnMutation:
    def test_org_update_writes_immutable_audit_row(self, api_client):
        owner, profile = _make_retailer("audit_org_owner", "Audit Org Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)

        resp = api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org.id}),
            {"name": "Renamed Org"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK

        row = OrgAuditLog.objects.get(
            organization=org,
            object_type=OrgAuditLog.OBJECT_ORGANIZATION,
            object_id=str(org.id),
        )
        assert row.action == OrgAuditLog.ACTION_UPDATE
        assert row.actor_id == owner.id
        assert row.summary_before["name"] != "Renamed Org"
        assert row.summary_after["name"] == "Renamed Org"
        assert row.created_at is not None

    def test_staff_assign_writes_unified_audit_row(self, api_client):
        owner, profile = _make_retailer("audit_staff_owner", "Audit Staff Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": "audit_cashier",
                "password": "CashPass123!",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

        staff_user = User.objects.get(username="audit_cashier")
        row = OrgAuditLog.objects.get(
            organization=org,
            object_type="staff_membership",
            object_id=str(staff_user.id),
            action=OrgAuditLog.ACTION_GRANT,
        )
        assert row.actor_id == owner.id
        assert row.summary_after["role_slug"] == "cashier"

    def test_api_key_create_writes_unified_audit_row(self, api_client):
        owner, profile = _make_retailer("audit_key_owner", "Audit Key Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            reverse("organization_api_keys", kwargs={"org_id": org.id}),
            {"name": "Partner Key", "scopes": ["partner.org.read"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

        row = OrgAuditLog.objects.get(
            organization=org,
            object_type="api_key",
            action=OrgAuditLog.ACTION_GRANT,
        )
        assert row.actor_id == owner.id
        assert row.summary_after["name"] == "Partner Key"
        assert "partner.org.read" in row.summary_after["scopes"]


@pytest.mark.django_db
class TestAuditLogReadAccess:
    def test_cashier_without_audit_read_gets_403(self, api_client):
        owner, profile = _make_retailer("audit_denied_owner", "Denied Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug="cashier")

        api_client.force_authenticate(user=owner)
        api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": "no_audit_cashier",
                "password": "CashPass123!",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        cashier = User.objects.get(username="no_audit_cashier")
        api_client.force_authenticate(user=cashier)

        resp = api_client.get(_audit_url(org.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "audit" in resp.data["error"].lower()

    def test_owner_can_read_audit_log(self, api_client):
        owner, profile = _make_retailer("audit_read_owner", "Read Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)

        api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org.id}),
            {"name": "Readable Org"},
            format="json",
        )

        resp = api_client.get(_audit_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] >= 1
        assert resp.data["results"][0]["object_type"] == OrgAuditLog.OBJECT_ORGANIZATION

    def test_cross_tenant_cannot_read_audit_log(self, api_client):
        owner_a, profile_a = _make_retailer("audit_tenant_a", "Tenant A")
        org_a = profile_a.organization
        owner_b, _profile_b = _make_retailer("audit_tenant_b", "Tenant B")

        api_client.force_authenticate(user=owner_a)
        api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org_a.id}),
            {"name": "Secret Org A"},
            format="json",
        )

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(_audit_url(org_a.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert OrgAuditLog.objects.filter(organization=org_a).exists()


@pytest.mark.django_db
class TestAuditLogAppendOnly:
    def test_mutations_on_audit_endpoint_not_allowed(self, api_client):
        owner, profile = _make_retailer("audit_append_owner", "Append Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)

        post_resp = api_client.post(_audit_url(org.id), {}, format="json")
        patch_resp = api_client.patch(_audit_url(org.id), {}, format="json")
        delete_resp = api_client.delete(_audit_url(org.id))

        assert post_resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert patch_resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert delete_resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
class TestAuditLogLocationFilter:
    def test_location_id_filter_returns_only_matching_rows(self, api_client):
        owner, profile = _make_retailer("audit_loc_owner", "Loc Shop")
        org = profile.organization
        other_profile = RetailerProfile.objects.create(
            user=User.objects.create_user(
                username="other_loc_user",
                email="other@test.com",
                password="TestPass123!",
                user_type="retailer",
                is_active=True,
            ),
            organization=org,
            shop_name="Second Location",
            address_line1="2 Main",
            city="City",
            state="State",
            pincode="110002",
            is_active=True,
        )

        record_org_audit_event(
            organization=org,
            actor=owner,
            action=OrgAuditLog.ACTION_UPDATE,
            object_type="location_profile",
            object_id=profile.id,
            summary_before={"shop_name": "Old"},
            summary_after={"shop_name": profile.shop_name},
            location=profile,
        )
        record_org_audit_event(
            organization=org,
            actor=owner,
            action=OrgAuditLog.ACTION_UPDATE,
            object_type="location_profile",
            object_id=other_profile.id,
            summary_before={"shop_name": "Old"},
            summary_after={"shop_name": other_profile.shop_name},
            location=other_profile,
        )

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_audit_url(org.id), {"location_id": profile.id})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["location"] == profile.id

    def test_invalid_location_id_for_org_returns_400(self, api_client):
        owner, profile = _make_retailer("audit_bad_loc", "Bad Loc Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)

        resp = api_client.get(_audit_url(org.id), {"location_id": 999999})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestAuditLogQueryBudget:
    """Hot audit list must stay bounded (no N+1, tenant-scoped queryset)."""

    def test_audit_list_query_count(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("audit_q_owner", "Audit Query Shop")
        org = profile.organization
        record_org_audit_event(
            organization=org,
            actor=owner,
            action=OrgAuditLog.ACTION_UPDATE,
            object_type=OrgAuditLog.OBJECT_ORGANIZATION,
            object_id=org.id,
            summary_before={"name": "Before"},
            summary_after={"name": "After"},
        )
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(3):
            resp = api_client.get(_audit_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["actor_username"] == owner.username

    def test_audit_list_scales_with_rows(
        self, api_client, django_assert_num_queries
    ):
        owner, profile = _make_retailer("audit_q_scale", "Audit Scale Shop")
        org = profile.organization
        for i in range(5):
            record_org_audit_event(
                organization=org,
                actor=owner,
                action=OrgAuditLog.ACTION_UPDATE,
                object_type=OrgAuditLog.OBJECT_ORGANIZATION,
                object_id=org.id,
                summary_before={"i": i},
                summary_after={"i": i + 1},
            )
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(3):
            resp = api_client.get(_audit_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 5
        assert len(resp.data["results"]) == 5

    def test_audit_list_with_location_filter_query_count(
        self, api_client, django_assert_num_queries
    ):
        owner, profile = _make_retailer("audit_q_loc", "Audit Loc Filter Shop")
        org = profile.organization
        record_org_audit_event(
            organization=org,
            actor=owner,
            action=OrgAuditLog.ACTION_UPDATE,
            object_type="location_profile",
            object_id=profile.id,
            summary_before={"shop_name": "Old"},
            summary_after={"shop_name": profile.shop_name},
            location=profile,
        )
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(4):
            resp = api_client.get(_audit_url(org.id), {"location_id": profile.id})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1

    def test_cross_tenant_audit_list_denied_one_query(
        self, api_client, django_assert_num_queries
    ):
        owner_a, profile_a = _make_retailer("audit_iso_a", "Audit Iso A")
        owner_b, _profile_b = _make_retailer("audit_iso_b", "Audit Iso B")
        api_client.force_authenticate(user=owner_b)
        with django_assert_num_queries(1):
            resp = api_client.get(_audit_url(profile_a.organization_id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN
