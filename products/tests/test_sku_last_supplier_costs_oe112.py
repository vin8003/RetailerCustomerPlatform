"""
OE-112 / F-0045 — last supplier costs for a SKU from PI history (thin EXTEND).

Purchase-role read. Missing history is empty, not 0. Non-purchase 403.
Tenant-scoped. No PO / quote / cost-model invent.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory, PurchaseInvoice, PurchaseItem
from products.supplier_last_costs import last_supplier_cost_rows_for_product
from retailers.models import OrgRole, OrgStaffMembership, RetailerProfile, Supplier
from retailers.organization import ensure_organization_for_profile
from retailers.suppliers import PERM_PURCHASING_TERMS


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


def _make_product(shop, name):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=shop)
    return Product.objects.create(
        retailer=shop,
        name=name,
        category=category,
        price=Decimal("20.00"),
        quantity=10,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def _make_supplier(shop, name):
    return Supplier.objects.create(retailer=shop, company_name=name, is_active=True)


def _add_pi_line(shop, supplier, product, unit_cost, invoice_date, invoice_number):
    invoice = PurchaseInvoice.objects.create(
        retailer=shop,
        supplier=supplier,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        total_amount=unit_cost,
    )
    # created_at is auto; bump so same-day later rows win when needed
    PurchaseItem.objects.create(
        invoice=invoice,
        product=product,
        quantity=Decimal("1"),
        purchase_price=unit_cost,
        total=unit_cost,
    )
    return invoice


def _url(product_id):
    return reverse("erp-sku-last-supplier-costs", args=[product_id])


def _by_supplier(payload):
    return {row["supplier_id"]: row for row in payload["suppliers"]}


@pytest.mark.django_db
class TestLastSupplierCostRows:
    def test_latest_per_supplier_omits_missing(self):
        owner, shop = _make_retailer("oe112_rows_own", "OE112 Rows Shop")
        product = _make_product(shop, "OE112 Oil")
        cheap = _make_supplier(shop, "Cheap Co")
        dear = _make_supplier(shop, "Dear Co")
        _make_supplier(shop, "Never Sold")

        _add_pi_line(shop, cheap, product, Decimal("8.00"), date(2026, 1, 1), "INV-C-OLD")
        later = _add_pi_line(
            shop, cheap, product, Decimal("9.50"), date(2026, 3, 1), "INV-C-NEW"
        )
        dear_inv = _add_pi_line(
            shop, dear, product, Decimal("14.00"), date(2026, 2, 1), "INV-D-1"
        )

        rows = last_supplier_cost_rows_for_product(product)
        by_id = {row["supplier_id"]: row for row in rows}

        assert set(by_id) == {cheap.id, dear.id}
        assert by_id[cheap.id]["last_cost"] == Decimal("9.50")
        assert by_id[cheap.id]["invoice_id"] == later.id
        assert by_id[dear.id]["last_cost"] == Decimal("14.00")
        assert by_id[dear.id]["invoice_id"] == dear_inv.id
        assert Decimal("0.00") not in [row["last_cost"] for row in rows]

    def test_no_history_is_empty(self):
        owner, shop = _make_retailer("oe112_empty_own", "OE112 Empty Shop")
        product = _make_product(shop, "OE112 New SKU")
        assert last_supplier_cost_rows_for_product(product) == []

    def test_same_day_later_created_wins(self):
        owner, shop = _make_retailer("oe112_same_own", "OE112 Same Day Shop")
        product = _make_product(shop, "OE112 Dal")
        vendor = _make_supplier(shop, "Same Day Co")
        older = _add_pi_line(
            shop, vendor, product, Decimal("4.00"), date(2026, 1, 10), "INV-SD-1"
        )
        newer = _add_pi_line(
            shop, vendor, product, Decimal("6.00"), date(2026, 1, 10), "INV-SD-2"
        )
        now = timezone.now()
        PurchaseInvoice.objects.filter(pk=older.id).update(created_at=now - timedelta(hours=2))
        PurchaseInvoice.objects.filter(pk=newer.id).update(created_at=now)

        rows = last_supplier_cost_rows_for_product(product)
        assert len(rows) == 1
        assert rows[0]["last_cost"] == Decimal("6.00")
        assert rows[0]["invoice_id"] == newer.id


@pytest.mark.django_db
class TestSkuLastSupplierCostsApi:
    def test_purchase_role_sees_last_costs(self, api_client):
        owner, shop = _make_retailer("oe112_hit_own", "OE112 Hit Shop")
        product = _make_product(shop, "OE112 Atta")
        a = _make_supplier(shop, "Alpha Dist")
        b = _make_supplier(shop, "Beta Dist")
        _add_pi_line(shop, a, product, Decimal("10.00"), date(2026, 4, 1), "INV-A")
        _add_pi_line(shop, b, product, Decimal("18.00"), date(2026, 4, 2), "INV-B")
        buyer = _make_staff(shop.organization, "oe112_buyer", [PERM_PURCHASING_TERMS])

        api_client.force_authenticate(user=buyer)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["product_id"] == product.id
        by_id = _by_supplier(resp.data)
        assert set(by_id) == {a.id, b.id}
        assert by_id[a.id]["last_cost"] == "10.00"
        assert by_id[a.id]["supplier_name"] == "Alpha Dist"
        assert by_id[b.id]["last_cost"] == "18.00"

    def test_owner_sees_higher_cost_supplier(self, api_client):
        owner, shop = _make_retailer("oe112_owner", "OE112 Owner Shop")
        product = _make_product(shop, "OE112 Rice")
        low = _make_supplier(shop, "Low Cost")
        high = _make_supplier(shop, "High Cost")
        _add_pi_line(shop, low, product, Decimal("5.00"), date(2026, 5, 1), "INV-L")
        _add_pi_line(shop, high, product, Decimal("50.00"), date(2026, 5, 2), "INV-H")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        costs = {row["last_cost"] for row in resp.data["suppliers"]}
        assert costs == {"5.00", "50.00"}

    def test_missing_history_is_empty_not_zero(self, api_client):
        owner, shop = _make_retailer("oe112_miss_own", "OE112 Miss Shop")
        product = _make_product(shop, "OE112 Unbought")
        _make_supplier(shop, "Idle Vendor")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["suppliers"] == []
        assert "0.00" not in str(resp.data)
        assert 0 not in [row.get("last_cost") for row in resp.data["suppliers"]]

    def test_stored_zero_cost_is_history_not_missing(self, api_client):
        owner, shop = _make_retailer("oe112_zero_own", "OE112 Zero Shop")
        product = _make_product(shop, "OE112 Sample")
        vendor = _make_supplier(shop, "Sample Vendor")
        _add_pi_line(shop, vendor, product, Decimal("0.00"), date(2026, 6, 1), "INV-Z")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert len(resp.data["suppliers"]) == 1
        assert resp.data["suppliers"][0]["last_cost"] == "0.00"

    def test_cashier_gets_403(self, api_client):
        owner, shop = _make_retailer("oe112_cash_own", "OE112 Cash Shop")
        product = _make_product(shop, "OE112 Sugar")
        vendor = _make_supplier(shop, "Cash Vendor")
        _add_pi_line(shop, vendor, product, Decimal("7.00"), date(2026, 7, 1), "INV-CASH")
        cashier = _make_staff(shop.organization, "oe112_cashier", [])

        api_client.force_authenticate(user=cashier)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.data
        assert "purchase-role" in resp.data["error"]

    def test_customer_gets_403(self, api_client, customer):
        owner, shop = _make_retailer("oe112_cust_own", "OE112 Cust Shop")
        product = _make_product(shop, "OE112 Tea")
        api_client.force_authenticate(user=customer)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.data

    def test_unauthenticated_gets_401(self, api_client):
        owner, shop = _make_retailer("oe112_anon_own", "OE112 Anon Shop")
        product = _make_product(shop, "OE112 Salt")
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_is_404(self, api_client):
        owner_a, shop_a = _make_retailer("oe112_a_own", "OE112 A Shop")
        owner_b, shop_b = _make_retailer("oe112_b_own", "OE112 B Shop")
        product_a = _make_product(shop_a, "OE112 A SKU")
        vendor_a = _make_supplier(shop_a, "A Vendor")
        _add_pi_line(shop_a, vendor_a, product_a, Decimal("11.00"), date(2026, 8, 1), "INV-A-T")

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(_url(product_a.id))
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.data
        assert resp.data.get("suppliers") is None

    def test_other_tenant_history_not_mixed(self, api_client):
        owner_a, shop_a = _make_retailer("oe112_mix_a", "OE112 Mix A")
        owner_b, shop_b = _make_retailer("oe112_mix_b", "OE112 Mix B")
        product_a = _make_product(shop_a, "OE112 Mix SKU A")
        product_b = _make_product(shop_b, "OE112 Mix SKU B")
        vendor_a = _make_supplier(shop_a, "Mix A Vendor")
        vendor_b = _make_supplier(shop_b, "Mix B Vendor")
        _add_pi_line(shop_a, vendor_a, product_a, Decimal("3.00"), date(2026, 8, 2), "INV-MIX-A")
        _add_pi_line(shop_b, vendor_b, product_b, Decimal("99.00"), date(2026, 8, 2), "INV-MIX-B")

        api_client.force_authenticate(user=owner_a)
        resp = api_client.get(_url(product_a.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        by_id = _by_supplier(resp.data)
        assert set(by_id) == {vendor_a.id}
        assert vendor_b.id not in by_id
        assert by_id[vendor_a.id]["last_cost"] == "3.00"
