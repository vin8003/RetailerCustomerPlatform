"""
OE-97 / F-0001 — Organization (tenant parent) tests.

Covers: create+attach location 1, cross-tenant isolation, disable blocks
sessions without deleting history, 1:1 single-shop path, 401/403 matrix.
"""
import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.models import Organization, RetailerProfile
from retailers.organization import (
    ensure_organization_for_profile,
    user_is_org_staff_admin,
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
class TestOrganizationModel:
    def test_ensure_creates_one_to_one(self, retailer_user):
        profile = RetailerProfile.objects.create(
            user=retailer_user,
            shop_name="Kirana One",
            address_line1="A",
            city="C",
            state="S",
            pincode="110001",
        )
        org = ensure_organization_for_profile(profile)
        profile.refresh_from_db()
        assert profile.organization_id == org.id
        assert org.owner_id == retailer_user.id
        assert org.name == "Kirana One"
        assert list(org.locations.values_list("id", flat=True)) == [profile.id]

    def test_ensure_is_idempotent(self, retailer):
        first = ensure_organization_for_profile(retailer)
        second = ensure_organization_for_profile(retailer, name="Other")
        assert first.id == second.id
        assert Organization.objects.filter(owner=retailer.user).count() == 1

    def test_gstin_stays_on_shop_not_org(self, retailer):
        retailer.gst_number = "22AAAAA0000A1Z5"
        retailer.upi_id = "shop@upi"
        retailer.receipt_footer = "Thanks"
        retailer.save()
        org = retailer.organization
        assert not hasattr(org, "gst_number")
        assert retailer.gst_number == "22AAAAA0000A1Z5"
        assert org.locations.get().upi_id == "shop@upi"


@pytest.mark.django_db
class TestOrganizationAPIs:
    def test_owner_creates_org_and_attaches_shop(self, api_client):
        user, profile = _make_retailer("owner_a", "Shop A", with_org=False)
        assert profile.organization_id is None

        api_client.force_authenticate(user=user)
        url = reverse("organization_me")
        response = api_client.post(url, {"name": "Acme Retail"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        profile.refresh_from_db()
        assert profile.organization_id == response.data["id"]
        assert response.data["name"] == "Acme Retail"
        assert response.data["location_ids"] == [profile.id]
        assert response.data["location_count"] == 1
        assert response.data["owner"] == user.id

    def test_get_implicit_org_for_single_shop(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.get(reverse("organization_me"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == retailer.organization_id
        assert response.data["location_ids"] == [retailer.id]

    def test_profile_api_includes_implicit_org(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.get(reverse("get_retailer_profile"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["organization_id"] == retailer.organization_id
        assert response.data["organization_name"] == retailer.organization.name
        assert response.data["organization_is_active"] is True
        # Shop fields unchanged / not duplicated onto org
        assert response.data["shop_name"] == "Products Test Shop"

    def test_duplicate_create_leaves_resource_unchanged(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        org_id = retailer.organization_id
        name = retailer.organization.name
        response = api_client.post(
            reverse("organization_me"), {"name": "Hijack"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        retailer.organization.refresh_from_db()
        assert retailer.organization_id == org_id
        assert retailer.organization.name == name


@pytest.mark.django_db
class TestCrossTenantIsolation:
    def test_org_a_data_never_returned_to_org_b(self, api_client):
        user_a, profile_a = _make_retailer("iso_a", "Shop A")
        user_b, profile_b = _make_retailer("iso_b", "Shop B")
        org_a = profile_a.organization
        org_b = profile_b.organization

        api_client.force_authenticate(user=user_b)
        # Direct fetch of org A must not leak data
        response = api_client.get(
            reverse("organization_detail", kwargs={"org_id": org_a.id})
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "name" not in response.data or response.data.get("name") != org_a.name

        # Own org still works
        own = api_client.get(
            reverse("organization_detail", kwargs={"org_id": org_b.id})
        )
        assert own.status_code == status.HTTP_200_OK
        assert own.data["id"] == org_b.id
        assert own.data["name"] == org_b.name

    def test_cross_tenant_patch_forbidden_and_unchanged(self, api_client):
        user_a, profile_a = _make_retailer("patch_a", "Shop A")
        user_b, _profile_b = _make_retailer("patch_b", "Shop B")
        org_a = profile_a.organization
        original_name = org_a.name
        original_active = org_a.is_active

        api_client.force_authenticate(user=user_b)
        response = api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org_a.id}),
            {"name": "Hacked", "is_active": False},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        org_a.refresh_from_db()
        assert org_a.name == original_name
        assert org_a.is_active is original_active


@pytest.mark.django_db
class TestDisableTenantBlocksSessions:
    def test_disable_blocks_login_preserves_history(self, api_client):
        user, profile = _make_retailer("disabled_shop", "Disabled Shop")
        org = profile.organization

        api_client.force_authenticate(user=user)
        disable = api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org.id}),
            {"is_active": False},
            format="json",
        )
        assert disable.status_code == status.HTTP_200_OK
        assert disable.data["is_active"] is False

        # History retained
        org.refresh_from_db()
        profile.refresh_from_db()
        assert Organization.objects.filter(pk=org.pk).exists()
        assert RetailerProfile.objects.filter(pk=profile.pk).exists()
        assert profile.shop_name == "Disabled Shop"

        # New session blocked
        api_client.force_authenticate(user=None)
        login = api_client.post(
            reverse("retailer_login"),
            {"username": "disabled_shop", "password": "TestPass123!"},
        )
        assert login.status_code == status.HTTP_403_FORBIDDEN
        assert "tokens" not in login.data

        # Re-enable allows login again
        org.is_active = True
        org.save(update_fields=["is_active"])
        login_ok = api_client.post(
            reverse("retailer_login"),
            {"username": "disabled_shop", "password": "TestPass123!"},
        )
        assert login_ok.status_code == status.HTTP_200_OK
        assert "access" in login_ok.data["tokens"]


@pytest.mark.django_db
class TestOrgAuthzMatrix:
    def test_unauthenticated_gets_401(self, api_client, retailer):
        assert (
            api_client.get(reverse("organization_me")).status_code
            == status.HTTP_401_UNAUTHORIZED
        )
        assert (
            api_client.post(reverse("organization_me"), {}).status_code
            == status.HTTP_401_UNAUTHORIZED
        )
        assert (
            api_client.get(
                reverse(
                    "organization_detail",
                    kwargs={"org_id": retailer.organization_id},
                )
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )
        assert (
            api_client.patch(
                reverse(
                    "organization_detail",
                    kwargs={"org_id": retailer.organization_id},
                ),
                {"name": "X"},
                format="json",
            ).status_code
            == status.HTTP_401_UNAUTHORIZED
        )

    def test_customer_gets_403_resource_unchanged(self, api_client, customer, retailer):
        org = retailer.organization
        original = org.name
        api_client.force_authenticate(user=customer)

        assert (
            api_client.get(reverse("organization_me")).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert (
            api_client.patch(
                reverse("organization_detail", kwargs={"org_id": org.id}),
                {"name": "Customer Hijack"},
                format="json",
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )
        org.refresh_from_db()
        assert org.name == original

    def test_non_admin_patch_forbidden_resource_unchanged(self, api_client):
        """Shop user who is not org.owner cannot mutate (simulates future staff)."""
        owner, profile = _make_retailer("org_owner", "Owner Shop")
        staff = User.objects.create_user(
            username="shop_staff_sim",
            email="staff_sim@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        # Transfer profile ownership to staff while org.owner stays the original owner
        profile.user = staff
        profile.save(update_fields=["user"])
        org = profile.organization
        assert org.owner_id == owner.id
        assert not user_is_org_staff_admin(staff, org)

        api_client.force_authenticate(user=staff)
        # GET still allowed for the attached location's session (same tenant)
        get_resp = api_client.get(
            reverse("organization_detail", kwargs={"org_id": org.id})
        )
        assert get_resp.status_code == status.HTTP_200_OK

        original_name = org.name
        patch = api_client.patch(
            reverse("organization_detail", kwargs={"org_id": org.id}),
            {"name": "Should Not Apply", "is_active": False},
            format="json",
        )
        assert patch.status_code == status.HTTP_403_FORBIDDEN
        org.refresh_from_db()
        assert org.name == original_name
        assert org.is_active is True
