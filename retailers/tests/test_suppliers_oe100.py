"""
OE-100 / F-0041 thin EXTEND: supplier GSTIN, payment-terms gate, tenancy.
"""
from unittest.mock import MagicMock

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.models import OrgAuditLog, OrgRole, OrgStaffMembership, RetailerProfile, Supplier
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import ALL_PERMISSION_CODES
from retailers.serializers import SupplierSerializer
from retailers.suppliers import (
    DUPLICATE_GSTIN_MESSAGE,
    PERM_PURCHASING_TERMS,
    active_suppliers_for_org,
    gstin_exists_in_org,
    normalize_gstin,
    payment_terms_would_change,
)


GSTIN_A = "22AAAAA0000A1Z5"
GSTIN_B = "27AAAAA0000A1Z5"


def _make_retailer(username, shop_name):
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
    ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_staff(org, username, permissions):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    role = OrgRole.objects.create(
        organization=org,
        slug=f"role_{username}",
        name=f"Role {username}",
        permissions=list(permissions),
        is_system=False,
    )
    OrgStaffMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_active=True,
    )
    return user


def _gstin_duplicate_flagged(payload):
    flag = payload.get("gstin_duplicate")
    if flag is True:
        return True
    if flag in (False, None):
        return False
    if isinstance(flag, (list, tuple)) and flag:
        return str(flag[0]).lower() in ("true", "1")
    return False


@pytest.mark.django_db
class TestSupplierHelperUnits:
    def test_normalize_gstin_optional_and_uppercase(self):
        assert normalize_gstin("") == ""
        assert normalize_gstin("  22aaaaa0000a1z5  ") == GSTIN_A

    def test_normalize_gstin_rejects_invalid(self):
        from rest_framework.exceptions import ValidationError

        with pytest.raises(ValidationError):
            normalize_gstin("NOT-A-GSTIN")

    def test_payment_terms_echo_is_not_a_change(self):
        instance = type("S", (), {"payment_terms": "Net 30"})()
        assert payment_terms_would_change(instance, {"company_name": "X"}) is False
        assert payment_terms_would_change(instance, {"payment_terms": "Net 30"}) is False
        assert payment_terms_would_change(instance, {"payment_terms": "COD"}) is True
        assert payment_terms_would_change(None, {"company_name": "X"}) is False
        assert payment_terms_would_change(None, {"payment_terms": "COD"}) is True
        assert payment_terms_would_change(None, {"payment_terms": ""}) is False

    def test_gstin_exists_scoped_to_org(self):
        _owner_a, shop_a = _make_retailer("gst_org_a", "Shop A")
        _owner_b, shop_b = _make_retailer("gst_org_b", "Shop B")
        Supplier.objects.create(
            retailer=shop_a, company_name="A Co", gst_number=GSTIN_A
        )
        assert gstin_exists_in_org(shop_a.organization, GSTIN_A) is True
        assert gstin_exists_in_org(shop_b.organization, GSTIN_A) is False
        assert gstin_exists_in_org(shop_a.organization, GSTIN_B) is False

    def test_active_suppliers_picker_hides_inactive(self):
        owner, shop = _make_retailer("picker_owner", "Picker Shop")
        Supplier.objects.create(retailer=shop, company_name="Live", is_active=True)
        Supplier.objects.create(retailer=shop, company_name="Dead", is_active=False)
        names = set(
            active_suppliers_for_org(shop.organization).values_list(
                "company_name", flat=True
            )
        )
        assert names == {"Live"}


@pytest.mark.django_db
class TestSupplierCreateGstin:
    def test_create_without_gstin(self, api_client):
        owner, _shop = _make_retailer("sup_opt_gst", "Optional GST Shop")
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "No GSTIN Vendor"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["gst_number"] in ("", None)
        assert resp.data["company_name"] == "No GSTIN Vendor"
        assert resp.data["is_active"] is True
        assert resp.data["payment_terms"] in ("", None)

    def test_create_with_optional_gstin(self, api_client):
        owner, _shop = _make_retailer("sup_with_gst", "With GST Shop")
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "GST Vendor", "gst_number": GSTIN_A.lower()},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["gst_number"] == GSTIN_A

    def test_duplicate_gstin_flagged_same_org(self, api_client):
        owner, shop = _make_retailer("sup_dup_gst", "Dup GST Shop")
        Supplier.objects.create(
            retailer=shop, company_name="First", gst_number=GSTIN_A
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Second", "gst_number": GSTIN_A},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert _gstin_duplicate_flagged(resp.data) is True
        assert DUPLICATE_GSTIN_MESSAGE in str(resp.data.get("gst_number"))
        assert Supplier.objects.filter(retailer=shop).count() == 1

    def test_blank_gstin_not_treated_as_duplicate(self, api_client):
        owner, shop = _make_retailer("sup_blank_gst", "Blank GST Shop")
        Supplier.objects.create(retailer=shop, company_name="First Blank")
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Second Blank", "gst_number": ""},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert Supplier.objects.filter(retailer=shop).count() == 2

    def test_same_gstin_allowed_across_orgs(self, api_client):
        owner_a, shop_a = _make_retailer("sup_gst_a", "Org A Shop")
        owner_b, shop_b = _make_retailer("sup_gst_b", "Org B Shop")
        Supplier.objects.create(
            retailer=shop_a, company_name="A Vendor", gst_number=GSTIN_A
        )
        api_client.force_authenticate(user=owner_b)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "B Vendor", "gst_number": GSTIN_A},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["gst_number"] == GSTIN_A
        assert Supplier.objects.filter(retailer=shop_b, gst_number=GSTIN_A).exists()

    def test_serializer_duplicate_flag_without_api(self):
        owner, shop = _make_retailer("sup_ser_dup", "Ser Dup Shop")
        Supplier.objects.create(
            retailer=shop, company_name="Existing", gst_number=GSTIN_B
        )
        request = MagicMock()
        request.user = owner
        serializer = SupplierSerializer(
            data={"company_name": "Copy", "gst_number": GSTIN_B},
            context={"request": request},
        )
        assert not serializer.is_valid()
        assert _gstin_duplicate_flagged(serializer.errors) is True


@pytest.mark.django_db
class TestSupplierPaymentTermsGate:
    def test_owner_can_set_payment_terms(self, api_client):
        owner, shop = _make_retailer("terms_owner", "Terms Shop")
        api_client.force_authenticate(user=owner)
        create = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Terms Vendor", "payment_terms": "Net 30"},
            format="json",
        )
        assert create.status_code == status.HTTP_201_CREATED, create.data
        assert create.data["payment_terms"] == "Net 30"
        sid = create.data["id"]
        patch = api_client.patch(
            reverse("erp-supplier-detail", args=[sid]),
            {"payment_terms": "COD"},
            format="json",
        )
        assert patch.status_code == status.HTTP_200_OK, patch.data
        assert patch.data["payment_terms"] == "COD"
        assert OrgAuditLog.objects.filter(
            organization=shop.organization,
            object_type=OrgAuditLog.OBJECT_SUPPLIER,
            object_id=str(sid),
        ).exists()

    def test_cashier_cannot_change_payment_terms(self, api_client):
        owner, shop = _make_retailer("terms_cash_owner", "Cash Terms Shop")
        supplier = Supplier.objects.create(
            retailer=shop, company_name="Locked Terms", payment_terms="Net 15"
        )
        cashier = _make_staff(shop.organization, "terms_cashier", [])
        api_client.force_authenticate(user=cashier)
        resp = api_client.patch(
            reverse("erp-supplier-detail", args=[supplier.id]),
            {"payment_terms": "Net 45"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.data
        supplier.refresh_from_db()
        assert supplier.payment_terms == "Net 15"

    def test_cashier_can_echo_payment_terms_and_edit_name(self, api_client):
        owner, shop = _make_retailer("terms_echo_owner", "Echo Terms Shop")
        supplier = Supplier.objects.create(
            retailer=shop, company_name="Echo Vendor", payment_terms="Net 15"
        )
        cashier = _make_staff(shop.organization, "terms_echo_cashier", [])
        api_client.force_authenticate(user=cashier)
        echo = api_client.patch(
            reverse("erp-supplier-detail", args=[supplier.id]),
            {"company_name": "Renamed Vendor", "payment_terms": "Net 15"},
            format="json",
        )
        assert echo.status_code == status.HTTP_200_OK, echo.data
        assert echo.data["company_name"] == "Renamed Vendor"
        assert echo.data["payment_terms"] == "Net 15"

    def test_cashier_cannot_create_with_payment_terms(self, api_client):
        owner, shop = _make_retailer("terms_create_owner", "Create Terms Shop")
        cashier = _make_staff(shop.organization, "terms_create_cashier", [])
        api_client.force_authenticate(user=cashier)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Should Fail", "payment_terms": "Advance"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.data
        assert not Supplier.objects.filter(company_name="Should Fail").exists()

    def test_staff_with_perm_can_change_terms(self, api_client):
        owner, shop = _make_retailer("terms_perm_owner", "Perm Terms Shop")
        supplier = Supplier.objects.create(
            retailer=shop, company_name="Perm Vendor", payment_terms=""
        )
        buyer = _make_staff(
            shop.organization, "terms_buyer", [PERM_PURCHASING_TERMS]
        )
        api_client.force_authenticate(user=buyer)
        resp = api_client.patch(
            reverse("erp-supplier-detail", args=[supplier.id]),
            {"payment_terms": "Net 7"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["payment_terms"] == "Net 7"

    def test_purchasing_terms_in_catalog(self):
        assert PERM_PURCHASING_TERMS in ALL_PERMISSION_CODES


@pytest.mark.django_db
class TestSupplierTenancy:
    def test_tenant_a_cannot_read_or_mutate_tenant_b(self, api_client):
        owner_a, shop_a = _make_retailer("ten_a", "Tenant A Shop")
        owner_b, shop_b = _make_retailer("ten_b", "Tenant B Shop")
        supplier_b = Supplier.objects.create(
            retailer=shop_b,
            company_name="Secret Vendor",
            payment_terms="Net 30",
            gst_number=GSTIN_B,
        )
        api_client.force_authenticate(user=owner_a)
        listed = api_client.get(reverse("erp-supplier-list"))
        assert listed.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in listed.data["results"]]
        assert supplier_b.id not in ids

        detail = api_client.get(
            reverse("erp-supplier-detail", args=[supplier_b.id])
        )
        assert detail.status_code == status.HTTP_404_NOT_FOUND

        patched = api_client.patch(
            reverse("erp-supplier-detail", args=[supplier_b.id]),
            {"payment_terms": "Hacked", "company_name": "Stolen"},
            format="json",
        )
        assert patched.status_code == status.HTTP_404_NOT_FOUND
        supplier_b.refresh_from_db()
        assert supplier_b.company_name == "Secret Vendor"
        assert supplier_b.payment_terms == "Net 30"

        deleted = api_client.delete(
            reverse("erp-supplier-detail", args=[supplier_b.id])
        )
        assert deleted.status_code == status.HTTP_404_NOT_FOUND
        assert Supplier.objects.filter(pk=supplier_b.id).exists()

    def test_customer_cannot_manage_suppliers(self, api_client, customer):
        _owner, shop = _make_retailer("ten_cust_owner", "Cust Deny Shop")
        supplier = Supplier.objects.create(retailer=shop, company_name="Shop Vendor")
        api_client.force_authenticate(user=customer)
        listed = api_client.get(reverse("erp-supplier-list"))
        assert listed.status_code == status.HTTP_403_FORBIDDEN
        created = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Nope"},
            format="json",
        )
        assert created.status_code == status.HTTP_403_FORBIDDEN
        patched = api_client.patch(
            reverse("erp-supplier-detail", args=[supplier.id]),
            {"company_name": "Nope"},
            format="json",
        )
        assert patched.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_is_401(self, api_client):
        resp = api_client.get(reverse("erp-supplier-list"))
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_is_active_query_param_for_picker(self, api_client):
        owner, shop = _make_retailer("picker_q", "Picker Query Shop")
        live = Supplier.objects.create(
            retailer=shop, company_name="Live Co", is_active=True
        )
        Supplier.objects.create(
            retailer=shop, company_name="Dead Co", is_active=False
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.get(reverse("erp-supplier-list"), {"is_active": "true"})
        assert resp.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in resp.data["results"]]
        assert ids == [live.id]
