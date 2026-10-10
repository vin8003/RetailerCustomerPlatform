"""OE-131 review fix: existing cashiers keep order access after orders.* ships."""
import pytest
from django.urls import reverse

from retailers.models import OrgRole
from retailers.organization import ensure_org_rbac_bootstrap, user_has_org_permission
from retailers.tests.test_staff_roles import _make_retailer


@pytest.mark.django_db
class TestCashierDefaults:
    def test_new_org_cashier_has_order_access(self):
        _owner, profile = _make_retailer("cd_new", "CD New")
        role = OrgRole.objects.get(organization=profile.organization, slug="cashier")
        assert set(role.permissions) == {"orders.create", "orders.read"}

    def test_legacy_empty_cashier_role_is_backfilled(self):
        _owner, profile = _make_retailer("cd_legacy", "CD Legacy")
        org = profile.organization
        OrgRole.objects.filter(organization=org, slug="cashier").update(permissions=[])
        ensure_org_rbac_bootstrap(org)
        role = OrgRole.objects.get(organization=org, slug="cashier")
        assert set(role.permissions) == {"orders.create", "orders.read"}

    def test_customised_cashier_is_left_alone(self):
        _owner, profile = _make_retailer("cd_custom", "CD Custom")
        org = profile.organization
        OrgRole.objects.filter(organization=org, slug="cashier").update(
            permissions=["orders.read"]
        )
        ensure_org_rbac_bootstrap(org)
        role = OrgRole.objects.get(organization=org, slug="cashier")
        assert role.permissions == ["orders.read"]


@pytest.mark.django_db
class TestPosLocationErrors:
    def test_non_integer_location_id_is_400_not_403(self, api_client):
        owner, _profile = _make_retailer("cd_pos", "CD POS")
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            "/api/products/erp/pos-checkout/",
            {"items": [], "location_id": "abc"},
            format="json",
        )
        assert resp.status_code == 400
