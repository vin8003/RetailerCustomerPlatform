"""
OE-169 / F-0071 — purchase-role margin_percent on catalog reads (thin EXTEND).

List/detail/search reuse OE-118 draft-or-last-PI math. Missing cost is
null, not 0. Non-purchase omits the field. Tenant-scoped. POS no_page
follow-on is OE-284. No POS till block / PIN / threshold invent.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory, PurchaseInvoice, PurchaseItem
from products.serializers import ProductListSerializer
from products.supplier_last_costs import (
    last_pi_unit_costs_by_product_id,
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


def _make_location_profile(user, org, shop_name):
    return RetailerProfile.objects.create(
        user=user,
        organization=org,
        shop_name=shop_name,
        address_line1="2 Side",
        city="City",
        state="State",
        pincode="110002",
        is_active=True,
    )


def _make_customer(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
    )


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


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _margin(val):
    if val is None:
        return None
    return Decimal(str(val))


def _purchase_item_queries(queries):
    """PurchaseItem SELECTs (batch last-PI or per-SKU)."""
    hits = []
    for query in queries:
        sql = query["sql"]
        if "purchaseitem" in sql.lower().replace("_", ""):
            hits.append(sql)
    return hits


@pytest.mark.django_db
class TestLastPiUnitCostsByProductId:
    def test_latest_per_sku_skips_draft_and_other_shop(self):
        owner_a, shop_a = _make_retailer("oe169_batch_a", "OE169 Batch A")
        owner_b, shop_b = _make_retailer("oe169_batch_b", "OE169 Batch B")
        draft = _make_product(
            shop_a, "OE169 Draft", purchase_price=Decimal("12.00")
        )
        last_pi = _make_product(shop_a, "OE169 Last PI")
        missing = _make_product(shop_a, "OE169 Missing")
        other = _make_product(shop_b, "OE169 Other")
        vendor_a = _make_supplier(shop_a, "Batch A Vendor")
        vendor_b = _make_supplier(shop_b, "Batch B Vendor")
        older = _add_pi_line(
            shop_a, vendor_a, last_pi, Decimal("4.00"), date(2026, 1, 10), "INV-A1"
        )
        newer = _add_pi_line(
            shop_a, vendor_a, last_pi, Decimal("6.00"), date(2026, 1, 10), "INV-A2"
        )
        now = timezone.now()
        PurchaseInvoice.objects.filter(pk=older.id).update(
            created_at=now - timedelta(hours=2)
        )
        PurchaseInvoice.objects.filter(pk=newer.id).update(created_at=now)
        _add_pi_line(
            shop_b, vendor_b, other, Decimal("99.00"), date(2026, 8, 2), "INV-B"
        )

        costs = last_pi_unit_costs_by_product_id([draft, last_pi, missing, other])
        assert draft.id not in costs
        assert costs[last_pi.id] == Decimal("6.00")
        assert missing.id not in costs
        assert costs[other.id] == Decimal("99.00")


@pytest.mark.django_db
class TestCatalogMarginPercentReads:
    def test_purchase_role_list_detail_search_match_oe118_math(self, api_client):
        owner, shop = _make_retailer("oe169_hit_own", "OE169 Hit Shop")
        product = _make_product(
            shop,
            "OE169 Atta",
            price=Decimal("20.00"),
            purchase_price=Decimal("10.00"),
        )
        expected = selling_margin_percent(Decimal("20.00"), Decimal("10.00"))
        assert expected == Decimal("50.00")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE169 Atta"}
        )

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert search.status_code == status.HTTP_200_OK, search.data

        list_row = _row_by_id(listed.data, product.id)
        search_row = _row_by_id(search.data, product.id)
        for row in (list_row, detail.data, search_row):
            assert row["margin_percent"] == "50.00"
            assert _margin(row["margin_percent"]) == expected

    def test_purchase_staff_uses_last_pi_when_no_draft(self, api_client):
        owner, shop = _make_retailer("oe169_staff_own", "OE169 Staff Shop")
        buyer = _make_staff(shop.organization, "oe169_buyer", [PERM_PURCHASING_TERMS])
        loc = _make_location_profile(buyer, shop.organization, "OE169 Buyer Loc")
        product = _make_product(loc, "OE169 Rice", price=Decimal("20.00"))
        vendor = _make_supplier(loc, "PI Vendor")
        _add_pi_line(loc, vendor, product, Decimal("8.00"), date(2026, 5, 1), "INV-L")

        api_client.force_authenticate(user=buyer)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE169 Rice"}
        )

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert search.status_code == status.HTTP_200_OK, search.data
        for row in (
            _row_by_id(listed.data, product.id),
            detail.data,
            _row_by_id(search.data, product.id),
        ):
            assert row["margin_percent"] == "60.00"

    def test_missing_cost_is_null_not_zero(self, api_client):
        owner, shop = _make_retailer("oe169_miss_own", "OE169 Miss Shop")
        product = _make_product(shop, "OE169 Unbought")

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE169 Unbought"}
        )

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert search.status_code == status.HTTP_200_OK, search.data
        for row in (
            _row_by_id(listed.data, product.id),
            detail.data,
            _row_by_id(search.data, product.id),
        ):
            assert "margin_percent" in row
            assert row["margin_percent"] is None
            assert row["margin_percent"] != 0

    def test_stored_zero_cost_is_real_not_missing(self, api_client):
        owner, shop = _make_retailer("oe169_zero_own", "OE169 Zero Shop")
        product = _make_product(
            shop, "OE169 Sample", purchase_price=Decimal("0.00")
        )

        api_client.force_authenticate(user=owner)
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert detail.data["margin_percent"] == "100.00"

    def test_cashier_omits_field(self, api_client):
        owner, shop = _make_retailer("oe169_cash_own", "OE169 Cash Shop")
        cashier = _make_staff(shop.organization, "oe169_cashier", [])
        loc = _make_location_profile(cashier, shop.organization, "OE169 Cash Loc")
        product = _make_product(
            loc, "OE169 Sugar", purchase_price=Decimal("7.00")
        )

        api_client.force_authenticate(user=cashier)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE169 Sugar"}
        )

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert search.status_code == status.HTTP_200_OK, search.data
        for row in (
            _row_by_id(listed.data, product.id),
            detail.data,
            _row_by_id(search.data, product.id),
        ):
            assert "margin_percent" not in row
            assert row.get("id") == product.id

    def test_serializer_without_flag_omits_field(self):
        owner, shop = _make_retailer("oe169_ser_own", "OE169 Ser Shop")
        product = _make_product(
            shop, "OE169 Ser SKU", purchase_price=Decimal("9.00")
        )
        data = ProductListSerializer(product).data
        assert "margin_percent" not in data

    def test_public_catalog_omits_field(self, api_client):
        owner, shop = _make_retailer("oe169_pub_own", "OE169 Public Shop")
        product = _make_product(
            shop, "OE169 Public Milk", purchase_price=Decimal("5.00")
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert public.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        assert "margin_percent" not in row

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe169_auth_own", "OE169 Auth Shop")
        product = _make_product(shop, "OE169 Auth Rice", purchase_price=Decimal("3.00"))
        customer = _make_customer("oe169_auth_cust")

        anon_list = api_client.get(reverse("get_retailer_products"))
        anon_detail = api_client.get(
            reverse("get_product_detail", args=[product.id])
        )
        assert anon_list.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon_detail.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        cust_list = api_client.get(reverse("get_retailer_products"))
        cust_detail = api_client.get(
            reverse("get_product_detail", args=[product.id])
        )
        assert cust_list.status_code == status.HTTP_403_FORBIDDEN
        assert cust_detail.status_code == status.HTTP_403_FORBIDDEN
        assert cust_list.data.get("margin_percent") is None
        assert cust_detail.data.get("margin_percent") is None

    def test_no_cross_tenant_read(self, api_client):
        owner_a, shop_a = _make_retailer("oe169_ten_a", "OE169 Tenant A")
        owner_b, shop_b = _make_retailer("oe169_ten_b", "OE169 Tenant B")
        product_a = _make_product(
            shop_a, "OE169 A SKU", purchase_price=Decimal("11.00")
        )
        product_b = _make_product(
            shop_b, "OE169 B SKU", purchase_price=Decimal("13.00")
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("get_retailer_products"))
        detail = api_client.get(reverse("get_product_detail", args=[product_a.id]))
        search = api_client.get(
            reverse("search_products"), {"search": "OE169 A SKU"}
        )

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_404_NOT_FOUND
        assert detail.data.get("margin_percent") is None
        assert search.status_code == status.HTTP_200_OK
        list_ids = {row["id"] for row in listed.data["results"]}
        search_ids = {row["id"] for row in search.data["results"]}
        assert product_a.id not in list_ids
        assert product_a.id not in search_ids
        assert product_b.id in list_ids
        assert _row_by_id(listed.data, product_b.id)["margin_percent"] == "35.00"

    def test_other_tenant_pi_not_used_as_cost(self, api_client):
        owner_a, shop_a = _make_retailer("oe169_mix_a", "OE169 Mix A")
        owner_b, shop_b = _make_retailer("oe169_mix_b", "OE169 Mix B")
        product_a = _make_product(shop_a, "OE169 Mix SKU A")
        product_b = _make_product(shop_b, "OE169 Mix SKU B")
        vendor_b = _make_supplier(shop_b, "Mix B Vendor")
        _add_pi_line(
            shop_b, vendor_b, product_b, Decimal("99.00"), date(2026, 8, 2), "INV-MIX-B"
        )

        api_client.force_authenticate(user=owner_a)
        detail = api_client.get(reverse("get_product_detail", args=[product_a.id]))
        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert detail.data["margin_percent"] is None

    def test_list_avoids_per_product_last_pi_lookup(self, api_client):
        owner, shop = _make_retailer("oe169_q_own", "OE169 Query Shop")
        vendor = _make_supplier(shop, "Query Vendor")
        products = []
        for i in range(3):
            product = _make_product(shop, f"OE169 Query Dal {i + 1}")
            _add_pi_line(
                shop,
                vendor,
                product,
                Decimal("8.00"),
                date(2026, 5, i + 1),
                f"INV-Q{i}",
            )
            products.append(product)

        api_client.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as list_ctx:
            listed = api_client.get(reverse("get_retailer_products"))

        assert listed.status_code == status.HTTP_200_OK, listed.data
        assert len(_purchase_item_queries(list_ctx.captured_queries)) == 1
        for product in products:
            row = _row_by_id(listed.data, product.id)
            assert row["margin_percent"] == "60.00"
