"""
OE-284 / F-0071 follow-on — purchase-role margin_percent on POS no_page.

Same OE-118/OE-169 draft-or-last-PI math. Missing cost is null, not 0.
Cashiers / public omit the field. Tenant-scoped. No till-block / PIN.
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
from products.supplier_last_costs import selling_margin_percent
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


def _purchase_item_queries(queries):
    hits = []
    for query in queries:
        sql = query["sql"]
        if "purchaseitem" in sql.lower().replace("_", ""):
            hits.append(sql)
    return hits


def _pos(api_client):
    return api_client.get(reverse("get_retailer_products"), {"no_page": "true"})


@pytest.mark.django_db
class TestPosNoPageMarginPercent:
    def test_purchase_role_matches_oe169_math(self, api_client):
        owner, shop = _make_retailer("oe284_hit_own", "OE284 Hit Shop")
        product = _make_product(
            shop,
            "OE284 Atta",
            price=Decimal("20.00"),
            purchase_price=Decimal("10.00"),
        )
        expected = selling_margin_percent(Decimal("20.00"), Decimal("10.00"))
        assert expected == Decimal("50.00")

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        row = _row_by_id(pos.data, product.id)
        assert row["margin_percent"] == "50.00"
        assert Decimal(str(row["margin_percent"])) == expected

    def test_purchase_staff_uses_last_pi_when_no_draft(self, api_client):
        owner, shop = _make_retailer("oe284_staff_own", "OE284 Staff Shop")
        buyer = _make_staff(shop.organization, "oe284_buyer", [PERM_PURCHASING_TERMS])
        loc = _make_location_profile(buyer, shop.organization, "OE284 Buyer Loc")
        product = _make_product(loc, "OE284 Rice", price=Decimal("20.00"))
        vendor = _make_supplier(loc, "PI Vendor")
        _add_pi_line(loc, vendor, product, Decimal("8.00"), date(2026, 5, 1), "INV-L")

        api_client.force_authenticate(user=buyer)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        assert _row_by_id(pos.data, product.id)["margin_percent"] == "60.00"

    def test_missing_cost_is_null_not_zero(self, api_client):
        owner, shop = _make_retailer("oe284_miss_own", "OE284 Miss Shop")
        product = _make_product(shop, "OE284 Unbought")

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        row = _row_by_id(pos.data, product.id)
        assert "margin_percent" in row
        assert row["margin_percent"] is None
        assert row["margin_percent"] != 0

    def test_stored_zero_cost_is_real_not_missing(self, api_client):
        owner, shop = _make_retailer("oe284_zero_own", "OE284 Zero Shop")
        product = _make_product(
            shop, "OE284 Sample", purchase_price=Decimal("0.00")
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        assert _row_by_id(pos.data, product.id)["margin_percent"] == "100.00"

    def test_draft_cost_wins_over_last_pi(self, api_client):
        owner, shop = _make_retailer("oe284_draft_own", "OE284 Draft Shop")
        product = _make_product(
            shop, "OE284 Draft Oil", purchase_price=Decimal("10.00")
        )
        vendor = _make_supplier(shop, "Draft Vendor")
        _add_pi_line(
            shop, vendor, product, Decimal("8.00"), date(2026, 5, 1), "INV-DRAFT"
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        assert _row_by_id(pos.data, product.id)["margin_percent"] == "50.00"

    def test_last_pi_zero_cost_is_real_not_missing(self, api_client):
        owner, shop = _make_retailer("oe284_pi0_own", "OE284 PI Zero Shop")
        product = _make_product(shop, "OE284 Free Sample")
        vendor = _make_supplier(shop, "Free Vendor")
        _add_pi_line(
            shop, vendor, product, Decimal("0.00"), date(2026, 6, 1), "INV-FREE"
        )

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        assert _row_by_id(pos.data, product.id)["margin_percent"] == "100.00"

    def test_cashier_omits_field(self, api_client):
        owner, shop = _make_retailer("oe284_cash_own", "OE284 Cash Shop")
        cashier = _make_staff(shop.organization, "oe284_cashier", [])
        loc = _make_location_profile(cashier, shop.organization, "OE284 Cash Loc")
        product = _make_product(
            loc, "OE284 Sugar", purchase_price=Decimal("7.00")
        )

        api_client.force_authenticate(user=cashier)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        row = _row_by_id(pos.data, product.id)
        assert "margin_percent" not in row
        assert row.get("id") == product.id

    def test_public_catalog_omits_field(self, api_client):
        owner, shop = _make_retailer("oe284_pub_own", "OE284 Public Shop")
        product = _make_product(
            shop, "OE284 Public Milk", purchase_price=Decimal("5.00")
        )

        public = api_client.get(
            reverse("get_retailer_products_public", args=[shop.id])
        )
        assert public.status_code == status.HTTP_200_OK
        row = _row_by_id(public.data, product.id)
        assert "margin_percent" not in row

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe284_auth_own", "OE284 Auth Shop")
        _make_product(shop, "OE284 Auth Rice", purchase_price=Decimal("3.00"))
        customer = _make_customer("oe284_auth_cust")

        anon = _pos(api_client)
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED
        assert anon.data.get("margin_percent") is None

        api_client.force_authenticate(user=customer)
        cust = _pos(api_client)
        assert cust.status_code == status.HTTP_403_FORBIDDEN
        assert cust.data.get("margin_percent") is None

    def test_no_cross_tenant_read(self, api_client):
        owner_a, shop_a = _make_retailer("oe284_ten_a", "OE284 Tenant A")
        owner_b, shop_b = _make_retailer("oe284_ten_b", "OE284 Tenant B")
        product_a = _make_product(
            shop_a, "OE284 A SKU", purchase_price=Decimal("11.00")
        )
        product_b = _make_product(
            shop_b, "OE284 B SKU", purchase_price=Decimal("13.00")
        )

        api_client.force_authenticate(user=owner_b)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in pos.data}
        assert product_a.id not in ids
        assert product_b.id in ids
        assert _row_by_id(pos.data, product_b.id)["margin_percent"] == "35.00"

    def test_other_tenant_pi_not_used_as_cost(self, api_client):
        owner_a, shop_a = _make_retailer("oe284_mix_a", "OE284 Mix A")
        owner_b, shop_b = _make_retailer("oe284_mix_b", "OE284 Mix B")
        product_a = _make_product(shop_a, "OE284 Mix SKU A")
        product_b = _make_product(shop_b, "OE284 Mix SKU B")
        vendor_b = _make_supplier(shop_b, "Mix B Vendor")
        _add_pi_line(
            shop_b, vendor_b, product_b, Decimal("99.00"), date(2026, 8, 2), "INV-MIX-B"
        )

        api_client.force_authenticate(user=owner_a)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        assert _row_by_id(pos.data, product_a.id)["margin_percent"] is None

    def test_pos_avoids_per_product_last_pi_lookup(self, api_client):
        owner, shop = _make_retailer("oe284_q_own", "OE284 Query Shop")
        vendor = _make_supplier(shop, "Query Vendor")
        products = []
        for i in range(3):
            product = _make_product(shop, f"OE284 Query Dal {i + 1}")
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
        with CaptureQueriesContext(connection) as pos_ctx:
            pos = _pos(api_client)

        assert pos.status_code == status.HTTP_200_OK, pos.data
        assert len(_purchase_item_queries(pos_ctx.captured_queries)) == 1
        for product in products:
            row = _row_by_id(pos.data, product.id)
            assert row["margin_percent"] == "60.00"

    def test_latest_last_pi_wins_same_shop(self, api_client):
        owner, shop = _make_retailer("oe284_latest_own", "OE284 Latest Shop")
        product = _make_product(shop, "OE284 Latest Dal")
        vendor = _make_supplier(shop, "Latest Vendor")
        older = _add_pi_line(
            shop, vendor, product, Decimal("4.00"), date(2026, 1, 10), "INV-OLD"
        )
        newer = _add_pi_line(
            shop, vendor, product, Decimal("5.00"), date(2026, 1, 10), "INV-NEW"
        )
        now = timezone.now()
        PurchaseInvoice.objects.filter(pk=older.id).update(
            created_at=now - timedelta(hours=2)
        )
        PurchaseInvoice.objects.filter(pk=newer.id).update(created_at=now)

        api_client.force_authenticate(user=owner)
        pos = _pos(api_client)
        assert pos.status_code == status.HTTP_200_OK, pos.data
        assert _row_by_id(pos.data, product.id)["margin_percent"] == "75.00"
