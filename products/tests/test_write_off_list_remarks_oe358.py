"""
OE-358 / F follow-on — optional remarks on write-off list rows.

Echo ProductInventoryLog.remarks only when the attribute exists.
Missing field or null stays null (no invented remarks from reason).
Auth/tenancy unchanged. READ only. Dummy hosts only.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.models import Product, ProductCategory, ProductInventoryLog
from products.serializers import ProductSearchSerializer
from products.write_off import REASON_DAMAGE, write_off_stock
from products.write_off_list import WriteOffListSerializer, inventory_log_remarks
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY_A = "8903581111111"
PRIMARY_B = "8903582222222"
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


def _ledger_url():
    return reverse("get_inventory_ledger")


def _write_off_url(product_id):
    return reverse("write_off_product", args=[product_id])


def _log_table_reads(captured):
    return [
        query["sql"]
        for query in captured.captured_queries
        if "product_inventory_log" in query["sql"].lower()
        and query["sql"].lstrip().upper().startswith("SELECT")
    ]


class TestInventoryLogRemarksHelper:
    def test_missing_attribute_is_none(self):
        assert not hasattr(ProductInventoryLog, "remarks")
        log = SimpleNamespace(reason=REASON_DAMAGE)
        assert inventory_log_remarks(log) is None

    def test_none_log_is_none(self):
        assert inventory_log_remarks(None) is None

    def test_echoes_when_attribute_exists(self):
        log = SimpleNamespace(reason=REASON_DAMAGE, remarks="crushed bag")
        assert inventory_log_remarks(log) == "crushed bag"

    def test_null_passthrough(self):
        log = SimpleNamespace(reason=REASON_DAMAGE, remarks=None)
        assert inventory_log_remarks(log) is None

    def test_empty_passthrough(self):
        log = SimpleNamespace(reason=REASON_DAMAGE, remarks="")
        assert inventory_log_remarks(log) == ""

    def test_does_not_invent_from_reason(self):
        log = SimpleNamespace(reason=REASON_DAMAGE)
        assert inventory_log_remarks(log) is None
        assert inventory_log_remarks(log) != log.reason


@pytest.mark.django_db
class TestWriteOffListRemarks:
    def test_model_has_no_remarks_field(self):
        field_names = {field.name for field in ProductInventoryLog._meta.get_fields()}
        assert "remarks" not in field_names
        assert "reason" in field_names

    def test_serializer_includes_remarks_null_on_this_stack(self):
        owner, shop = _make_retailer("oe358_ser_own", "OE358 Ser Shop")
        product = _make_product(shop, "OE358 Atta", barcode=PRIMARY_A)
        log = _log(product, owner, reason=REASON_DAMAGE)
        assert not hasattr(log, "remarks")

        data = WriteOffListSerializer(log).data
        assert "remarks" in data
        assert data["remarks"] is None
        assert data["reason"] == REASON_DAMAGE
        assert data["product_id"] == product.id
        assert data["product_name"] == product.name
        assert data["barcode"] == PRIMARY_A
        assert data["id"] == log.id

    def test_serializer_echoes_remarks_when_attribute_exists(self):
        owner, shop = _make_retailer("oe358_echo_own", "OE358 Echo Shop")
        product = _make_product(shop, "OE358 Sugar", barcode=PRIMARY_B)
        log = _log(product, owner, reason=REASON_DAMAGE)
        log.remarks = "wet carton"

        data = WriteOffListSerializer(log).data
        assert data["remarks"] == "wet carton"
        assert data["reason"] == REASON_DAMAGE

    def test_serializer_null_and_empty_passthrough(self):
        owner, shop = _make_retailer("oe358_pass_own", "OE358 Pass Shop")
        product = _make_product(shop, "OE358 Salt", barcode=PRIMARY_A)
        log = _log(product, owner, reason=REASON_DAMAGE)

        log.remarks = None
        assert WriteOffListSerializer(log).data["remarks"] is None

        log.remarks = ""
        assert WriteOffListSerializer(log).data["remarks"] == ""

    def test_ledger_list_includes_null_remarks(self, api_client):
        owner, shop = _make_retailer("oe358_led_own", "OE358 Ledger Shop")
        product = _make_product(shop, "OE358 Rice", barcode=PRIMARY_A, quantity=Decimal("10.000"))
        write_off_stock(
            product_id=product.id,
            retailer=shop,
            quantity=Decimal("2.000"),
            reason=REASON_DAMAGE,
            created_by=owner,
        )

        api_client.force_authenticate(user=owner)
        response = api_client.get(
            _ledger_url(),
            {"product_id": product.id, "reason": REASON_DAMAGE},
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        row = response.data[0]
        assert row["remarks"] is None
        assert row["reason"] == REASON_DAMAGE
        assert row["log_type"] == "damaged"
        assert row["product_id"] == product.id
        assert row["product_name"] == product.name
        assert row["barcode"] == PRIMARY_A

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("oe358_auth_own", "OE358 Auth Shop")
        product = _make_product(shop, "OE358 Auth Rice", barcode=PRIMARY_A)
        _log(product, owner, reason=REASON_DAMAGE)
        customer = _make_customer("oe358_auth_cust")

        anon = api_client.get(_ledger_url(), {"product_id": product.id})
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_ledger_url(), {"product_id": product.id})
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_product_still_404(self, api_client):
        owner_a, shop_a = _make_retailer("oe358_ten_a", "OE358 Tenant A")
        owner_b, shop_b = _make_retailer("oe358_ten_b", "OE358 Tenant B")
        product_a = _make_product(shop_a, "OE358 A SKU", barcode=PRIMARY_A)
        product_b = _make_product(shop_b, "OE358 B SKU", barcode=PRIMARY_B)
        _log(product_a, owner_a, reason=REASON_DAMAGE)
        _log(product_b, owner_b, reason=REASON_DAMAGE)

        api_client.force_authenticate(user=owner_b)
        cross = api_client.get(_ledger_url(), {"product_id": product_a.id})
        own = api_client.get(_ledger_url(), {"reason": REASON_DAMAGE})

        assert cross.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        assert len(own.data) == 1
        assert own.data[0]["product_id"] == product_b.id
        assert own.data[0]["remarks"] is None
        assert all(row["product_id"] != product_a.id for row in own.data)

    def test_write_off_post_remarks_is_ignored(self, api_client):
        owner, shop = _make_retailer("oe358_write_own", "OE358 Write Shop")
        product = _make_product(
            shop, "OE358 Write Rice", barcode=PRIMARY_A, quantity=Decimal("6.000")
        )

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            _write_off_url(product.id),
            {
                "quantity": "1.000",
                "reason": REASON_DAMAGE,
                "remarks": "do not persist",
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        assert "remarks" not in created.data
        log = ProductInventoryLog.objects.get(pk=created.data["id"])
        assert not hasattr(log, "remarks")
        assert log.reason == REASON_DAMAGE

    def test_select_related_log_adds_no_remarks_query(self):
        owner, shop = _make_retailer("oe358_n1_own", "OE358 N1 Shop")
        logs = []
        for idx in range(3):
            product = _make_product(
                shop, f"OE358 N1 {idx}", barcode=f"89035800000{idx}"
            )
            logs.append(_log(product, owner, reason=REASON_DAMAGE))
        for log, note in zip(logs, ("broken", "leaked", None)):
            log.remarks = note

        loaded = list(
            ProductInventoryLog.objects.select_related("product", "created_by")
            .filter(id__in=[log.id for log in logs])
            .order_by("id")
        )
        for row, note in zip(loaded, ("broken", "leaked", None)):
            row.remarks = note

        with CaptureQueriesContext(connection) as captured:
            data = WriteOffListSerializer(loaded, many=True).data

        assert [row["remarks"] for row in data] == ["broken", "leaked", None]
        assert _log_table_reads(captured) == []

    def test_shop_wide_reason_query_budget(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("oe358_q_own", "OE358 Query Shop")
        for i in range(5):
            product = _make_product(
                shop, f"OE358 Q{i}", barcode=f"89035810000{i}", quantity=Decimal("5.000")
            )
            write_off_stock(
                product_id=product.id,
                retailer=shop,
                quantity=Decimal("1.000"),
                reason=REASON_DAMAGE,
                created_by=owner,
            )

        api_client.force_authenticate(user=owner)
        # RetailerProfile get + one select_related(product, created_by) log fetch.
        with django_assert_num_queries(2):
            response = api_client.get(_ledger_url(), {"reason": REASON_DAMAGE})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 5
        assert all(row["remarks"] is None for row in response.data)

    def test_product_search_serializer_meta_stays_without_remarks(self):
        assert "remarks" not in ProductSearchSerializer.Meta.fields
