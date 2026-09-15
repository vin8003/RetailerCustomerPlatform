"""
OE-100 / F-0041 thin EXTEND: supplier GSTIN, payment-terms gate, tenancy.
"""
from unittest.mock import MagicMock

import pytest
from django.db import IntegrityError
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from retailers.models import OrgAuditLog, OrgRole, OrgStaffMembership, RetailerProfile, Supplier
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import ALL_PERMISSION_CODES
from retailers.serializers import SupplierSerializer
from retailers.suppliers import (
    DUPLICATE_GSTIN_MESSAGE,
    PAYMENT_TERMS_WHITESPACE_MESSAGE,
    PERM_PURCHASING_TERMS,
    UNIQ_ORG_SUPPLIER_GSTIN,
    active_suppliers_for_org,
    assert_payment_terms_not_whitespace_only,
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
    return str(flag).lower() in ("true", "1")


@pytest.mark.django_db
class TestSupplierHelperUnits:
    def test_normalize_gstin_optional_and_uppercase(self):
        assert normalize_gstin("") == ""
        assert normalize_gstin(None) == ""
        assert normalize_gstin("   ") == ""
        assert normalize_gstin("  22aaaaa0000a1z5  ") == GSTIN_A

    def test_normalize_gstin_rejects_invalid(self):
        from rest_framework.exceptions import ValidationError

        with pytest.raises(ValidationError):
            normalize_gstin("NOT-A-GSTIN")

    def test_payment_terms_echo_is_not_a_change(self):
        instance = type("S", (), {"payment_terms": "Net 30"})()
        assert payment_terms_would_change(instance, {"company_name": "X"}) is False
        assert payment_terms_would_change(instance, {"payment_terms": "Net 30"}) is False
        assert payment_terms_would_change(instance, {"payment_terms": "  Net 30  "}) is False
        assert payment_terms_would_change(instance, {"payment_terms": "COD"}) is True
        assert payment_terms_would_change(None, {"company_name": "X"}) is False
        assert payment_terms_would_change(None, {"payment_terms": "COD"}) is True
        assert payment_terms_would_change(None, {"payment_terms": ""}) is False

    def test_payment_terms_whitespace_only_is_rejected(self):
        from rest_framework.exceptions import ValidationError

        instance = type("S", (), {"payment_terms": "Net 30"})()
        assert payment_terms_would_change(instance, {"payment_terms": "   "}) is True
        with pytest.raises(ValidationError) as exc_info:
            assert_payment_terms_not_whitespace_only({"payment_terms": "   "})
        assert PAYMENT_TERMS_WHITESPACE_MESSAGE in str(exc_info.value.detail)

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


def _second_shop_same_org(org, username, shop_name):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    return RetailerProfile.objects.create(
        user=user,
        organization=org,
        shop_name=shop_name,
        address_line1="2 Main",
        city="City",
        state="State",
        pincode="110002",
        is_active=True,
    )


@pytest.mark.django_db
class TestSupplierGstinDbConstraint:
    def test_orm_null_gstin_stored_as_blank(self):
        _owner, shop = _make_retailer("gst_orm_null", "ORM Null GST Shop")
        row = Supplier.objects.create(
            retailer=shop, company_name="Null GST", gst_number=None
        )
        row.refresh_from_db()
        assert row.gst_number == ""

    def test_db_rejects_duplicate_gstin_same_org(self):
        _owner, shop = _make_retailer("gst_db_dup", "DB Dup GST Shop")
        Supplier.objects.create(
            retailer=shop, company_name="First", gst_number=GSTIN_A
        )
        with pytest.raises(IntegrityError):
            Supplier.objects.create(
                retailer=shop, company_name="Second", gst_number=GSTIN_A
            )

    def test_db_rejects_duplicate_gstin_across_shops_same_org(self):
        _owner, shop_a = _make_retailer("gst_db_multi", "DB Multi A")
        shop_b = _second_shop_same_org(
            shop_a.organization, "gst_db_multi_b", "DB Multi B"
        )
        Supplier.objects.create(
            retailer=shop_a, company_name="Loc A", gst_number=GSTIN_A
        )
        with pytest.raises(IntegrityError):
            Supplier.objects.create(
                retailer=shop_b, company_name="Loc B", gst_number=GSTIN_A
            )

    def test_db_allows_same_gstin_other_org_and_blank_repeat(self):
        _owner_a, shop_a = _make_retailer("gst_db_a", "DB Org A")
        _owner_b, shop_b = _make_retailer("gst_db_b", "DB Org B")
        Supplier.objects.create(
            retailer=shop_a, company_name="A Vendor", gst_number=GSTIN_A
        )
        other = Supplier.objects.create(
            retailer=shop_b, company_name="B Vendor", gst_number=GSTIN_A
        )
        assert other.gst_number == GSTIN_A
        Supplier.objects.create(retailer=shop_a, company_name="Blank 1", gst_number="")
        Supplier.objects.create(retailer=shop_a, company_name="Blank 2", gst_number=None)
        assert (
            Supplier.objects.filter(retailer=shop_a, gst_number="").count() == 2
        )

    def test_integrity_error_maps_to_duplicate_flag(self, api_client, monkeypatch):
        owner, shop = _make_retailer("gst_db_race", "DB Race Shop")
        Supplier.objects.create(
            retailer=shop, company_name="First", gst_number=GSTIN_A
        )
        monkeypatch.setattr(
            "retailers.suppliers.gstin_exists_in_org", lambda *args, **kwargs: False
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Racy", "gst_number": GSTIN_A},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert _gstin_duplicate_flagged(resp.data) is True
        assert DUPLICATE_GSTIN_MESSAGE in str(resp.data.get("gst_number"))
        assert Supplier.objects.filter(retailer=shop).count() == 1
        assert any(
            getattr(constraint, "name", "") == UNIQ_ORG_SUPPLIER_GSTIN
            for constraint in Supplier._meta.constraints
        )

    def test_integrity_error_maps_to_duplicate_flag_on_update(
        self, api_client, monkeypatch
    ):
        owner, shop = _make_retailer("gst_db_race_upd", "DB Race Upd Shop")
        Supplier.objects.create(
            retailer=shop, company_name="First", gst_number=GSTIN_A
        )
        other = Supplier.objects.create(
            retailer=shop, company_name="Second", gst_number=GSTIN_B
        )
        monkeypatch.setattr(
            "retailers.suppliers.gstin_exists_in_org", lambda *args, **kwargs: False
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("erp-supplier-detail", args=[other.id]),
            {"gst_number": GSTIN_A},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert _gstin_duplicate_flagged(resp.data) is True
        other.refresh_from_db()
        assert other.gst_number == GSTIN_B

    def test_update_fields_still_stamps_organization(self):
        _owner, shop = _make_retailer("gst_stamp_upd", "Stamp Org Shop")
        row = Supplier.objects.create(retailer=shop, company_name="Stamp Me")
        Supplier.objects.filter(pk=row.pk).update(organization=None)
        row.refresh_from_db()
        assert row.organization_id is None
        row.is_active = False
        row.save(update_fields=["is_active"])
        row.refresh_from_db()
        assert row.organization_id == shop.organization_id
        assert row.is_active is False


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

    def test_null_and_blank_gstin_normalize_and_may_repeat(self, api_client):
        owner, shop = _make_retailer("sup_null_gst", "Null GST Shop")
        api_client.force_authenticate(user=owner)
        created = []
        for name, body in (
            ("Null Vendor", {"company_name": "Null Vendor", "gst_number": None}),
            ("Empty Vendor", {"company_name": "Empty Vendor", "gst_number": ""}),
            ("Omitted Vendor", {"company_name": "Omitted Vendor"}),
        ):
            resp = api_client.post(reverse("erp-supplier-list"), body, format="json")
            assert resp.status_code == status.HTTP_201_CREATED, (name, resp.data)
            assert resp.data["gst_number"] == ""
            created.append(resp.data["id"])
        stored = list(
            Supplier.objects.filter(pk__in=created).values_list("gst_number", flat=True)
        )
        assert stored == ["", "", ""]

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

    def test_whitespace_only_payment_terms_rejected_on_change(self, api_client):
        owner, shop = _make_retailer("terms_ws_owner", "WS Terms Shop")
        supplier = Supplier.objects.create(
            retailer=shop, company_name="WS Vendor", payment_terms="Net 15"
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("erp-supplier-detail", args=[supplier.id]),
            {"payment_terms": "   "},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert PAYMENT_TERMS_WHITESPACE_MESSAGE in str(resp.data)
        supplier.refresh_from_db()
        assert supplier.payment_terms == "Net 15"

    def test_payment_terms_are_trimmed(self, api_client):
        owner, _shop = _make_retailer("terms_trim_owner", "Trim Terms Shop")
        api_client.force_authenticate(user=owner)
        create = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Trim Vendor", "payment_terms": "  Net 30  "},
            format="json",
        )
        assert create.status_code == status.HTTP_201_CREATED, create.data
        assert create.data["payment_terms"] == "Net 30"
        sid = create.data["id"]
        echo = api_client.patch(
            reverse("erp-supplier-detail", args=[sid]),
            {"payment_terms": "  Net 30  "},
            format="json",
        )
        assert echo.status_code == status.HTTP_200_OK, echo.data
        assert echo.data["payment_terms"] == "Net 30"

    def test_whitespace_only_payment_terms_rejected_on_create(self, api_client):
        owner, shop = _make_retailer("terms_ws_create", "WS Create Shop")
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "WS Create Vendor", "payment_terms": " \t "},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.data
        assert PAYMENT_TERMS_WHITESPACE_MESSAGE in str(resp.data)
        assert not Supplier.objects.filter(retailer=shop).exists()


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


@pytest.mark.django_db
class TestSupplierQueryBudget:
    """List + create must stay bounded (no N+1, tenant-scoped queryset)."""

    def test_list_query_count(self, api_client, django_assert_num_queries):
        owner, shop = _make_retailer("sup_q_list", "Query List Shop")
        Supplier.objects.create(retailer=shop, company_name="Vendor 1")
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(4):
            resp = api_client.get(reverse("erp-supplier-list"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1

    def test_list_scales_with_rows(self, api_client, django_assert_num_queries):
        owner, shop = _make_retailer("sup_q_scale", "Query Scale Shop")
        for i in range(8):
            Supplier.objects.create(retailer=shop, company_name=f"Vendor {i}")
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(4):
            resp = api_client.get(reverse("erp-supplier-list"))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 8

    def test_create_query_count(self, api_client, django_assert_num_queries):
        owner, _shop = _make_retailer("sup_q_create", "Query Create Shop")
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(8):
            resp = api_client.post(
                reverse("erp-supplier-list"),
                {"company_name": "Budget Vendor", "gst_number": GSTIN_A},
                format="json",
            )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data["gst_number"] == GSTIN_A
