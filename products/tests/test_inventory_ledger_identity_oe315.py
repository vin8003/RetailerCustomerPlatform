"""
OE-315 / F follow-on — product identity on inventory-ledger rows.

Ledger rows echo the same SKU identity already on product list:
product_id (list id), product_name (list name), barcode (list barcode).
Null/empty barcode stays null/empty. Auth/tenancy unchanged. READ only.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory, ProductInventoryLog
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903151111111"
PRIMARY_B = "8903152222222"
REASON_UPDATE = "Product update"


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


def _make_customer(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
    )


def _make_product(retailer, name, barcode=None, **kwargs):
    category = ProductCategory.objects.create(
        name=f"{name} Cat", retailer=retailer
    )
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "barcode": barcode,
        "price": Decimal("20.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "piece",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _log(product, owner, reason=REASON_UPDATE, qty=Decimal("1.000")):
    return ProductInventoryLog.objects.create(
        product=product,
        log_type="added",
        quantity_change=qty,
        previous_quantity=product.quantity,
        new_quantity=product.quantity + qty,
        reason=reason,
        created_by=owner,
    )


def _rows(payload):
    return payload if isinstance(payload, list) else payload.get("results") or []


def _list_row(payload, product_id):
    for row in _rows(payload):
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from list payload")


def _ledger_url():
    return reverse("get_inventory_ledger")


def _list_url():
    return reverse("get_retailer_products")


def _assert_identity_matches_list(ledger_row, list_row, product, log):
    assert ledger_row["id"] == log.id
    assert ledger_row["product_id"] == list_row["id"] == product.id
    assert ledger_row["product_name"] == list_row["name"] == product.name
    assert ledger_row["barcode"] == list_row["barcode"]
    assert ledger_row["barcode"] == product.barcode
    assert "log_type" in ledger_row
    assert "reason" in ledger_row


@pytest.mark.django_db
class TestInventoryLedgerProductIdentity:
    def test_ledger_identity_matches_product_list(self, api_client):
        owner, shop = _make_retailer("oe315_hit_own", "OE315 Identity Shop")
        atta = _make_product(shop, "OE315 Atta", barcode=PRIMARY_A)
        biscuits = _make_product(shop, "OE315 Biscuits", barcode=PRIMARY_B)
        atta_log = _log(atta, owner)
        biscuits_log = _log(biscuits, owner)

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())
        ledger = api_client.get(_ledger_url(), {"reason": REASON_UPDATE})

        assert listed.status_code == status.HTTP_200_OK
        assert ledger.status_code == status.HTTP_200_OK
        assert len(ledger.data) == 2

        by_log = {row["id"]: row for row in ledger.data}
        _assert_identity_matches_list(
            by_log[atta_log.id], _list_row(listed.data, atta.id), atta, atta_log
        )
        _assert_identity_matches_list(
            by_log[biscuits_log.id],
            _list_row(listed.data, biscuits.id),
            biscuits,
            biscuits_log,
        )

    def test_null_and_empty_barcode_passthrough(self, api_client):
        owner, shop = _make_retailer("oe315_null_own", "OE315 Null Shop")
        loose = _make_product(shop, "OE315 Loose Rice", barcode=None)
        blank = _make_product(shop, "OE315 Blank Atta", barcode="")
        assert loose.barcode is None
        assert blank.barcode == ""
        loose_log = _log(loose, owner)
        blank_log = _log(blank, owner)

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())
        ledger = api_client.get(_ledger_url(), {"reason": REASON_UPDATE})

        assert listed.status_code == status.HTTP_200_OK
        assert ledger.status_code == status.HTTP_200_OK
        by_log = {row["id"]: row for row in ledger.data}
        _assert_identity_matches_list(
            by_log[loose_log.id], _list_row(listed.data, loose.id), loose, loose_log
        )
        _assert_identity_matches_list(
            by_log[blank_log.id], _list_row(listed.data, blank.id), blank, blank_log
        )
        assert by_log[loose_log.id]["barcode"] is None
        assert by_log[blank_log.id]["barcode"] == ""

    def test_product_id_filter_includes_identity(self, api_client):
        owner, shop = _make_retailer("oe315_pid_own", "OE315 Pid Shop")
        atta = _make_product(shop, "OE315 Pid Atta", barcode=PRIMARY_A)
        other = _make_product(shop, "OE315 Pid Other", barcode=PRIMARY_B)
        atta_log = _log(atta, owner)
        _log(other, owner)

        api_client.force_authenticate(user=owner)
        listed = api_client.get(_list_url())
        ledger = api_client.get(_ledger_url(), {"product_id": atta.id})

        assert ledger.status_code == status.HTTP_200_OK
        assert [row["id"] for row in ledger.data] == [atta_log.id]
        _assert_identity_matches_list(
            ledger.data[0], _list_row(listed.data, atta.id), atta, atta_log
        )

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe315_auth_own", "OE315 Auth Shop")
        product = _make_product(shop, "OE315 Auth Rice", barcode=PRIMARY_A)
        _log(product, owner)
        customer = _make_customer("oe315_auth_cust")

        anon = api_client.get(_ledger_url(), {"product_id": product.id})
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_ledger_url(), {"product_id": product.id})
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_product_still_404(self, api_client):
        owner_a, shop_a = _make_retailer("oe315_ten_a", "OE315 Tenant A")
        owner_b, shop_b = _make_retailer("oe315_ten_b", "OE315 Tenant B")
        product_a = _make_product(shop_a, "OE315 A SKU", barcode=PRIMARY_A)
        product_b = _make_product(shop_b, "OE315 B SKU", barcode=PRIMARY_B)
        _log(product_a, owner_a)
        _log(product_b, owner_b)

        api_client.force_authenticate(user=owner_b)
        cross = api_client.get(_ledger_url(), {"product_id": product_a.id})
        own = api_client.get(_ledger_url(), {"reason": REASON_UPDATE})

        assert cross.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        assert len(own.data) == 1
        assert own.data[0]["product_id"] == product_b.id
        assert own.data[0]["product_name"] == product_b.name
        assert own.data[0]["barcode"] == PRIMARY_B
        assert all(row["product_id"] != product_a.id for row in own.data)

    def test_shop_wide_identity_query_budget(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("oe315_q_own", "OE315 Query Shop")
        logs = []
        for i in range(5):
            product = _make_product(
                shop, f"OE315 Q{i}", barcode=f"89031500000{i}"
            )
            logs.append(_log(product, owner))

        api_client.force_authenticate(user=owner)
        # RetailerProfile get + one select_related(product, created_by) log fetch.
        with django_assert_num_queries(2):
            response = api_client.get(_ledger_url(), {"reason": REASON_UPDATE})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 5
        names = {row["product_name"] for row in response.data}
        assert names == {f"OE315 Q{i}" for i in range(5)}
        assert {row["id"] for row in response.data} == {log.id for log in logs}
