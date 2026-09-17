"""
OE-118 / F-0046 — purchase-role margin% preview (thin EXTEND).

Selling price vs draft (Product.purchase_price) or last PI cost.
Missing cost is null, not 0. Non-purchase 403. Tenant-scoped.
No PO / policy / override invent.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory, PurchaseInvoice, PurchaseItem
from products.supplier_last_costs import (
    draft_or_last_pi_cost,
    last_pi_unit_cost_for_product,
    selling_margin_percent,
)
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


def _make_product(shop, name, price=Decimal("20.00"), purchase_price=None):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=shop)
    return Product.objects.create(
        retailer=shop,
        name=name,
        category=category,
        price=price,
        purchase_price=purchase_price,
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
    PurchaseItem.objects.create(
        invoice=invoice,
        product=product,
        quantity=Decimal("1"),
        purchase_price=unit_cost,
        total=unit_cost,
    )
    return invoice


def _url(product_id):
    return reverse("erp-sku-margin-preview", args=[product_id])


@pytest.mark.django_db
class TestDraftOrLastPiCost:
    def test_draft_sku_price_wins_over_last_pi(self):
        owner, shop = _make_retailer("oe118_rows_own", "OE118 Rows Shop")
        product = _make_product(
            shop, "OE118 Oil", purchase_price=Decimal("12.00")
        )
        vendor = _make_supplier(shop, "Last PI Co")
        _add_pi_line(shop, vendor, product, Decimal("8.00"), date(2026, 1, 1), "INV-OLD")

        cost, source = draft_or_last_pi_cost(product)
        assert cost == Decimal("12.00")
        assert source == "draft"
        assert last_pi_unit_cost_for_product(product) == Decimal("8.00")

    def test_last_pi_when_draft_missing(self):
        owner, shop = _make_retailer("oe118_last_own", "OE118 Last Shop")
        product = _make_product(shop, "OE118 Dal")
        vendor = _make_supplier(shop, "Only PI Co")
        older = _add_pi_line(
            shop, vendor, product, Decimal("4.00"), date(2026, 1, 10), "INV-SD-1"
        )
        newer = _add_pi_line(
            shop, vendor, product, Decimal("6.00"), date(2026, 1, 10), "INV-SD-2"
        )
        now = timezone.now()
        PurchaseInvoice.objects.filter(pk=older.id).update(
            created_at=now - timedelta(hours=2)
        )
        PurchaseInvoice.objects.filter(pk=newer.id).update(created_at=now)

        cost, source = draft_or_last_pi_cost(product)
        assert cost == Decimal("6.00")
        assert source == "last_pi"

    def test_missing_cost_is_none_not_zero(self):
        owner, shop = _make_retailer("oe118_empty_own", "OE118 Empty Shop")
        product = _make_product(shop, "OE118 New SKU")
        assert product.purchase_price is None
        assert last_pi_unit_cost_for_product(product) is None
        assert draft_or_last_pi_cost(product) == (None, None)

    def test_margin_percent_formula_and_nulls(self):
        assert selling_margin_percent(Decimal("20.00"), Decimal("12.00")) == Decimal(
            "40.00"
        )
        assert selling_margin_percent(Decimal("20.00"), Decimal("0.00")) == Decimal(
            "100.00"
        )
        assert selling_margin_percent(Decimal("20.00"), None) is None
        assert selling_margin_percent(Decimal("0.00"), Decimal("5.00")) is None


@pytest.mark.django_db
class TestSkuMarginPreviewApi:
    def test_purchase_role_sees_draft_margin(self, api_client):
        owner, shop = _make_retailer("oe118_hit_own", "OE118 Hit Shop")
        product = _make_product(
            shop,
            "OE118 Atta",
            price=Decimal("20.00"),
            purchase_price=Decimal("10.00"),
        )
        buyer = _make_staff(shop.organization, "oe118_buyer", [PERM_PURCHASING_TERMS])

        api_client.force_authenticate(user=buyer)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["product_id"] == product.id
        assert resp.data["selling_price"] == "20.00"
        assert resp.data["cost"] == "10.00"
        assert resp.data["cost_source"] == "draft"
        assert resp.data["margin_percent"] == "50.00"

    def test_owner_uses_last_pi_when_no_draft(self, api_client):
        owner, shop = _make_retailer("oe118_owner", "OE118 Owner Shop")
        product = _make_product(shop, "OE118 Rice", price=Decimal("20.00"))
        vendor = _make_supplier(shop, "PI Vendor")
        _add_pi_line(shop, vendor, product, Decimal("8.00"), date(2026, 5, 1), "INV-L")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["cost"] == "8.00"
        assert resp.data["cost_source"] == "last_pi"
        assert resp.data["margin_percent"] == "60.00"

    def test_missing_cost_is_null_not_zero(self, api_client):
        owner, shop = _make_retailer("oe118_miss_own", "OE118 Miss Shop")
        product = _make_product(shop, "OE118 Unbought")
        _make_supplier(shop, "Idle Vendor")

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["cost"] is None
        assert resp.data["cost_source"] is None
        assert resp.data["margin_percent"] is None
        assert resp.data["cost"] != 0
        assert resp.data["margin_percent"] != 0

    def test_stored_zero_cost_is_real_not_missing(self, api_client):
        owner, shop = _make_retailer("oe118_zero_own", "OE118 Zero Shop")
        product = _make_product(
            shop, "OE118 Sample", purchase_price=Decimal("0.00")
        )

        api_client.force_authenticate(user=owner)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["cost"] == "0.00"
        assert resp.data["cost_source"] == "draft"
        assert resp.data["margin_percent"] == "100.00"

    def test_cashier_gets_403(self, api_client):
        owner, shop = _make_retailer("oe118_cash_own", "OE118 Cash Shop")
        product = _make_product(
            shop, "OE118 Sugar", purchase_price=Decimal("7.00")
        )
        cashier = _make_staff(shop.organization, "oe118_cashier", [])

        api_client.force_authenticate(user=cashier)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.data
        assert "purchase-role" in resp.data["error"]
        assert resp.data.get("margin_percent") is None
        assert resp.data.get("cost") is None

    def test_customer_gets_403(self, api_client, customer):
        owner, shop = _make_retailer("oe118_cust_own", "OE118 Cust Shop")
        product = _make_product(shop, "OE118 Tea", purchase_price=Decimal("5.00"))
        api_client.force_authenticate(user=customer)
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.data
        assert resp.data.get("margin_percent") is None

    def test_unauthenticated_gets_401(self, api_client):
        owner, shop = _make_retailer("oe118_anon_own", "OE118 Anon Shop")
        product = _make_product(shop, "OE118 Salt")
        resp = api_client.get(_url(product.id))
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cross_tenant_is_404(self, api_client):
        owner_a, shop_a = _make_retailer("oe118_a_own", "OE118 A Shop")
        owner_b, shop_b = _make_retailer("oe118_b_own", "OE118 B Shop")
        product_a = _make_product(
            shop_a, "OE118 A SKU", purchase_price=Decimal("11.00")
        )

        api_client.force_authenticate(user=owner_b)
        resp = api_client.get(_url(product_a.id))
        assert resp.status_code == status.HTTP_404_NOT_FOUND, resp.data
        assert resp.data.get("cost") is None
        assert resp.data.get("margin_percent") is None

    def test_other_tenant_pi_not_used_as_cost(self, api_client):
        owner_a, shop_a = _make_retailer("oe118_mix_a", "OE118 Mix A")
        owner_b, shop_b = _make_retailer("oe118_mix_b", "OE118 Mix B")
        product_a = _make_product(shop_a, "OE118 Mix SKU A")
        product_b = _make_product(shop_b, "OE118 Mix SKU B")
        vendor_b = _make_supplier(shop_b, "Mix B Vendor")
        _add_pi_line(
            shop_b, vendor_b, product_b, Decimal("99.00"), date(2026, 8, 2), "INV-MIX-B"
        )

        api_client.force_authenticate(user=owner_a)
        resp = api_client.get(_url(product_a.id))
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data["cost"] is None
        assert resp.data["margin_percent"] is None
