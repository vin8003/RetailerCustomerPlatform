"""
OE-170 / F-0072 — additional_barcodes in POS/catalog lookup (thin EXTEND).

Search/lookup that already matches Product.barcode also resolves
Product.additional_barcodes with the same icontains semantics.
Tenant-scoped. No printer HAL or label formats.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory
from products.views import annotate_additional_barcodes_text, product_barcode_q
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile


ALT_CODE = "ALT170XYZ"
PRIMARY_CODE = "PRI170XYZ"


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


def _make_product(shop, name, *, barcode=None, extra_barcodes=None):
    category = ProductCategory.objects.create(name=f"{name} Cat", retailer=shop)
    return Product.objects.create(
        retailer=shop,
        name=name,
        category=category,
        price=Decimal("10.00"),
        quantity=5,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
        barcode=barcode,
        additional_barcodes=list(extra_barcodes or []),
    )


def _ids(payload):
    if isinstance(payload, list):
        return {item["id"] for item in payload}
    return {item["id"] for item in payload.get("results") or []}


@pytest.mark.django_db
class TestAdditionalBarcodeLookup:
    def test_pos_and_catalog_hit_additional_barcode(self, api_client):
        owner, shop = _make_retailer("oe170_hit_own", "OE170 Hit Shop")
        product = _make_product(
            shop, "OE170 Extra Oil", barcode=PRIMARY_CODE, extra_barcodes=[ALT_CODE]
        )
        decoy = _make_product(shop, "OE170 Other Dal", barcode="OTH170XYZ")
        api_client.force_authenticate(user=owner)

        pos = api_client.get(
            reverse("get_retailer_products"),
            {"search": ALT_CODE, "no_page": "true"},
        )
        catalog = api_client.get(reverse("search_products"), {"search": ALT_CODE})

        assert pos.status_code == status.HTTP_200_OK
        assert catalog.status_code == status.HTTP_200_OK
        assert product.id in _ids(pos.data)
        assert decoy.id not in _ids(pos.data)
        assert product.id in _ids(catalog.data)
        assert decoy.id not in _ids(catalog.data)

    def test_additional_barcode_case_matches_primary(self, api_client):
        owner, shop = _make_retailer("oe170_case_own", "OE170 Case Shop")
        product = _make_product(
            shop, "OE170 Case Oil", barcode="PRI170CASE", extra_barcodes=["ALT170CASE"]
        )
        api_client.force_authenticate(user=owner)

        pos = api_client.get(
            reverse("get_retailer_products"),
            {"search": "alt170case", "no_page": "true"},
        )
        assert pos.status_code == status.HTTP_200_OK
        assert product.id in _ids(pos.data)

    def test_no_cross_tenant_leak(self, api_client):
        owner_a, shop_a = _make_retailer("oe170_ten_a", "OE170 Tenant A")
        owner_b, shop_b = _make_retailer("oe170_ten_b", "OE170 Tenant B")
        product_a = _make_product(
            shop_a, "OE170 A Oil", barcode="PRI170A", extra_barcodes=[ALT_CODE]
        )
        _make_product(shop_b, "OE170 B Wheat", barcode="PRI170B")

        scoped = annotate_additional_barcodes_text(
            Product.objects.filter(retailer=shop_b)
        ).filter(product_barcode_q(ALT_CODE.lower()))
        assert list(scoped.values_list("id", flat=True)) == []

        api_client.force_authenticate(user=owner_b)
        pos = api_client.get(
            reverse("get_retailer_products"),
            {"search": ALT_CODE, "no_page": "true"},
        )
        catalog = api_client.get(reverse("search_products"), {"search": ALT_CODE})
        public = api_client.get(
            reverse("search_products_public", kwargs={"retailer_id": shop_b.id}),
            {"search": ALT_CODE},
        )

        assert pos.status_code == status.HTTP_200_OK
        assert catalog.status_code == status.HTTP_200_OK
        assert public.status_code == status.HTTP_200_OK
        assert product_a.id not in _ids(pos.data)
        assert product_a.id not in _ids(catalog.data)
        assert product_a.id not in _ids(public.data)

        api_client.force_authenticate(user=owner_a)
        own_pos = api_client.get(
            reverse("get_retailer_products"),
            {"search": ALT_CODE, "no_page": "true"},
        )
        assert product_a.id in _ids(own_pos.data)
