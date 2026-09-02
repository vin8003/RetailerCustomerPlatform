"""
OE-182 / F-0006 — Retailer and customer API versioning.

Covers: org-scoped API keys, scopes deny-by-default, revoke-on-next-request,
version prefix, 401/403 matrix, cross-tenant isolation, audit on grant/revoke,
existing JWT owner paths still work.
"""
import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.api_keys import create_org_api_key, revoke_org_api_key
from retailers.api_scopes import (
    ALL_API_SCOPE_CODES,
    API_SCOPE_CATALOG_VERSION,
    validate_scope_codes,
)
from retailers.models import OrgApiKey, OrgApiKeyAudit, OrgRole, RetailerProfile
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import ALL_PERMISSION_CODES, ROLE_SLUG_CASHIER


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


def _auth_api_key(api_client, raw_key):
    api_client.credentials(HTTP_AUTHORIZATION=f'Api-Key {raw_key}')


@pytest.mark.django_db
class TestApiScopeCatalog:
    def test_unknown_scopes_rejected(self):
        known, unknown = validate_scope_codes(
            ['partner.org.read', 'invented.scope', 'partner.org.write']
        )
        assert known == ['partner.org.read', 'partner.org.write']
        assert unknown == ['invented.scope']

    def test_jwt_scope_catalog_endpoint(self, api_client):
        user, profile = _make_retailer("scope_owner", "Scope Shop")
        org = profile.organization
        api_client.force_authenticate(user=user)
        resp = api_client.get(
            reverse("organization_api_scope_catalog", kwargs={"org_id": org.id})
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == API_SCOPE_CATALOG_VERSION
        codes = {s["code"] for s in resp.data["scopes"]}
        assert codes == set(ALL_API_SCOPE_CODES)


@pytest.mark.django_db
class TestApiKeyManagement:
    def test_owner_creates_key_with_audit_and_secret_once(self, api_client):
        owner, profile = _make_retailer("key_owner", "Key Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)

        resp = api_client.post(
            reverse("organization_api_keys", kwargs={"org_id": org.id}),
            {
                "name": "Partner A",
                "scopes": ["partner.org.read", "partner.locations.read"],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert "api_key" in resp.data
        raw = resp.data["api_key"]
        assert raw.startswith("oe_")
        assert resp.data["prefix"] in raw
        assert resp.data["scopes"] == [
            "partner.locations.read",
            "partner.org.read",
        ]

        assert OrgApiKeyAudit.objects.filter(
            organization=org,
            action=OrgApiKeyAudit.ACTION_GRANT,
            key_prefix=resp.data["prefix"],
        ).exists()

        # List never re-exposes the secret
        listed = api_client.get(
            reverse("organization_api_keys", kwargs={"org_id": org.id})
        )
        assert listed.status_code == status.HTTP_200_OK
        assert all("api_key" not in row for row in listed.data)

    def test_unknown_scope_on_create_rejected(self, api_client):
        owner, profile = _make_retailer("bad_scope_owner", "Bad Scope Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("organization_api_keys", kwargs={"org_id": org.id}),
            {"name": "Bad", "scopes": ["partner.org.read", "nope.scope"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert not OrgApiKey.objects.filter(organization=org).exists()

    def test_cashier_without_api_keys_manage_gets_403(self, api_client):
        owner, profile = _make_retailer("mgr_owner", "Mgr Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug=ROLE_SLUG_CASHIER)
        api_client.force_authenticate(user=owner)
        assign = api_client.post(
            reverse("organization_staff", kwargs={"org_id": org.id}),
            {
                "username": "key_cashier",
                "password": "CashPass123!",
                "email": "key_cashier@test.com",
                "role_id": cashier_role.id,
            },
            format="json",
        )
        assert assign.status_code == status.HTTP_201_CREATED
        cashier = User.objects.get(username="key_cashier")

        api_client.force_authenticate(user=cashier)
        before = OrgApiKey.objects.filter(organization=org).count()
        resp = api_client.post(
            reverse("organization_api_keys", kwargs={"org_id": org.id}),
            {"name": "Nope", "scopes": ["partner.org.read"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert OrgApiKey.objects.filter(organization=org).count() == before

    def test_unauthenticated_management_401(self, api_client):
        _owner, profile = _make_retailer("unauth_keys", "Unauth Keys")
        org = profile.organization
        resp = api_client.get(
            reverse("organization_api_keys", kwargs={"org_id": org.id})
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_cannot_manage_other_org_keys(self, api_client):
        owner_a, profile_a = _make_retailer("keys_a", "Keys A")
        _owner_b, profile_b = _make_retailer("keys_b", "Keys B")
        org_a = profile_a.organization
        org_b = profile_b.organization

        api_key, _raw = create_org_api_key(
            organization=org_a,
            name="A Key",
            scopes=["partner.org.read"],
            created_by=owner_a,
        )

        api_client.force_authenticate(user=_owner_b)
        resp = api_client.delete(
            reverse(
                "organization_api_key_detail",
                kwargs={"org_id": org_a.id, "key_id": api_key.id},
            )
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        api_key.refresh_from_db()
        assert api_key.is_active is True

        # Also cannot create under A while authenticated as B
        create_resp = api_client.post(
            reverse("organization_api_keys", kwargs={"org_id": org_a.id}),
            {"name": "Steal", "scopes": ["partner.org.read"]},
            format="json",
        )
        assert create_resp.status_code == status.HTTP_403_FORBIDDEN
        assert not OrgApiKey.objects.filter(organization=org_a, name="Steal").exists()
        assert org_b.id != org_a.id

    def test_revoke_writes_audit(self, api_client):
        owner, profile = _make_retailer("revoke_owner", "Revoke Shop")
        org = profile.organization
        api_key, _raw = create_org_api_key(
            organization=org,
            name="To Revoke",
            scopes=["partner.org.read"],
            created_by=owner,
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.delete(
            reverse(
                "organization_api_key_detail",
                kwargs={"org_id": org.id, "key_id": api_key.id},
            )
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_active"] is False
        assert OrgApiKeyAudit.objects.filter(
            organization=org,
            action=OrgApiKeyAudit.ACTION_REVOKE,
            key_prefix=api_key.prefix,
        ).exists()


@pytest.mark.django_db
class TestPartnerApiKeyAuthAndScopes:
    def test_unauthenticated_partner_route_401(self, api_client):
        resp = api_client.get(reverse("partner_v1_org"))
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_key_can_only_use_granted_scopes(self, api_client):
        owner, profile = _make_retailer("scoped_owner", "Scoped Shop")
        org = profile.organization
        api_key, raw = create_org_api_key(
            organization=org,
            name="Read Only Org",
            scopes=["partner.org.read"],
            created_by=owner,
        )
        assert api_key.has_scope("partner.org.read")

        _auth_api_key(api_client, raw)

        ok = api_client.get(reverse("partner_v1_org"))
        assert ok.status_code == status.HTTP_200_OK
        assert ok.data["id"] == org.id
        assert ok.data["name"] == org.name

        # Missing locations scope → 403
        denied = api_client.get(reverse("partner_v1_locations"))
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        # Missing write scope → 403 and name unchanged
        original = org.name
        patch = api_client.patch(
            reverse("partner_v1_org"),
            {"name": "Hacked Name"},
            format="json",
        )
        assert patch.status_code == status.HTTP_403_FORBIDDEN
        org.refresh_from_db()
        assert org.name == original

    def test_write_scope_can_rename_org(self, api_client):
        owner, profile = _make_retailer("write_owner", "Write Shop")
        org = profile.organization
        _key, raw = create_org_api_key(
            organization=org,
            name="Writer",
            scopes=["partner.org.read", "partner.org.write"],
            created_by=owner,
        )
        _auth_api_key(api_client, raw)
        resp = api_client.patch(
            reverse("partner_v1_org"),
            {"name": "Renamed Via Partner"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        org.refresh_from_db()
        assert org.name == "Renamed Via Partner"

    def test_revoked_key_rejected_on_next_request(self, api_client):
        owner, profile = _make_retailer("rev_next", "Rev Next Shop")
        org = profile.organization
        api_key, raw = create_org_api_key(
            organization=org,
            name="Ephemeral",
            scopes=["partner.org.read"],
            created_by=owner,
        )
        _auth_api_key(api_client, raw)
        assert api_client.get(reverse("partner_v1_org")).status_code == status.HTTP_200_OK

        revoke_org_api_key(api_key=api_key, actor=owner)
        next_resp = api_client.get(reverse("partner_v1_org"))
        assert next_resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_isolation(self, api_client):
        owner_a, profile_a = _make_retailer("iso_a", "Iso A")
        owner_b, profile_b = _make_retailer("iso_b", "Iso B")
        org_a = profile_a.organization
        org_b = profile_b.organization

        _key_a, raw_a = create_org_api_key(
            organization=org_a,
            name="A Partner",
            scopes=list(ALL_API_SCOPE_CODES),
            created_by=owner_a,
        )
        _key_b, _raw_b = create_org_api_key(
            organization=org_b,
            name="B Partner",
            scopes=list(ALL_API_SCOPE_CODES),
            created_by=owner_b,
        )

        _auth_api_key(api_client, raw_a)

        # Key A sees only org A
        org_resp = api_client.get(reverse("partner_v1_org"))
        assert org_resp.status_code == status.HTTP_200_OK
        assert org_resp.data["id"] == org_a.id
        assert org_resp.data["id"] != org_b.id

        locs = api_client.get(reverse("partner_v1_locations"))
        assert locs.status_code == status.HTTP_200_OK
        loc_ids = {row["id"] for row in locs.data}
        assert profile_a.id in loc_ids
        assert profile_b.id not in loc_ids

        # Key A cannot read B's location by id
        detail = api_client.get(
            reverse("partner_v1_location_detail", kwargs={"location_id": profile_b.id})
        )
        assert detail.status_code == status.HTTP_403_FORBIDDEN

        # Key A cannot rename org B (org comes from key — rename only hits A)
        before_b = org_b.name
        api_client.patch(
            reverse("partner_v1_org"),
            {"name": "Should Only Hit A"},
            format="json",
        )
        org_b.refresh_from_db()
        assert org_b.name == before_b
        org_a.refresh_from_db()
        assert org_a.name == "Should Only Hit A"

    def test_x_api_key_header_works(self, api_client):
        owner, profile = _make_retailer("xhdr", "X Header Shop")
        org = profile.organization
        _key, raw = create_org_api_key(
            organization=org,
            name="XHdr",
            scopes=["partner.org.read"],
            created_by=owner,
        )
        api_client.credentials(HTTP_X_API_KEY=raw)
        resp = api_client.get(reverse("partner_v1_org"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == org.id


@pytest.mark.django_db
class TestVersioningAndJwtCompatibility:
    def test_version_info_public(self, api_client):
        resp = api_client.get(reverse("api_v1_version_info"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["current"] == "v1"
        assert "v1" in resp.data["supported"]
        assert resp.data["sunset"]["v1"] is None
        assert "/api/v1/partner/" in resp.data["surfaces"]["partner"]

    def test_versioned_retailer_jwt_alias_still_works(self, api_client):
        owner, profile = _make_retailer("v1_jwt", "V1 JWT Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        # Unversioned path (existing apps)
        resp = api_client.get(
            reverse("organization_detail", kwargs={"org_id": org.id})
        )
        assert resp.status_code == status.HTTP_200_OK
        # Versioned alias
        resp_v1 = api_client.get(f"/api/v1/retailer/org/{org.id}/")
        assert resp_v1.status_code == status.HTTP_200_OK
        assert resp_v1.data["id"] == org.id

    def test_owner_still_has_api_keys_manage_in_catalog(self):
        assert "api_keys.manage" in ALL_PERMISSION_CODES
