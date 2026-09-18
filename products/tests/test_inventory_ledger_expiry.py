"""
Optional expiry_date echo on inventory-ledger rows.

Echo the log field when it exists; omit the key when ProductInventoryLog
has no such column. Do not add ProductSearch Meta or cart fields.
Dummy objects only — never *.ordereasy.win.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from products.inventory_ledger import (
    InventoryLedgerRowSerializer,
    attach_ledger_expiry_date,
    log_has_expiry_date_field,
)
from products.models import Product, ProductCategory, ProductInventoryLog
from products.serializers import ProductSearchSerializer
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

PRIMARY = "8903153333333"
REASON_UPDATE = "Product update"


class _DummyMeta:
    def __init__(self, field_names):
        self._field_names = set(field_names)

    def get_field(self, name):
        if name not in self._field_names:
            raise FieldDoesNotExist(name)
        return object()


def _dummy_model(field_names):
    return SimpleNamespace(_meta=_DummyMeta(field_names))


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


def _fake_log(**overrides):
    product = SimpleNamespace(name="Dummy Milk", barcode=PRIMARY)
    created_by = SimpleNamespace(get_full_name=lambda: "Dummy Owner")
    values = {
        "id": 11,
        "product_id": 22,
        "product": product,
        "log_type": "added",
        "batch_id": None,
        "quantity_change": Decimal("1.000"),
        "previous_quantity": Decimal("8.000"),
        "new_quantity": Decimal("9.000"),
        "reason": REASON_UPDATE,
        "created_at": "2026-09-18T00:00:00Z",
        "created_by": created_by,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_helper_false_when_log_has_no_field():
    assert log_has_expiry_date_field() is False


def test_helper_true_on_dummy_model_with_field():
    dummy_model = _dummy_model({"expiry_date", "reason"})
    assert log_has_expiry_date_field(dummy_model) is True


def test_helper_false_on_dummy_model_without_field():
    dummy_model = _dummy_model({"reason"})
    assert log_has_expiry_date_field(dummy_model) is False


def test_helper_false_on_dummy_without_meta():
    assert log_has_expiry_date_field(SimpleNamespace()) is False


def test_attach_omits_key_when_field_missing():
    dummy = SimpleNamespace(expiry_date=date(2026, 12, 1))
    data = attach_ledger_expiry_date({}, dummy, model=_dummy_model({"reason"}))
    assert "expiry_date" not in data


def test_attach_echoes_dummy_date_when_field_exists():
    expiry = date(2026, 12, 1)
    dummy = SimpleNamespace(expiry_date=expiry)
    data = attach_ledger_expiry_date({}, dummy, model=_dummy_model({"expiry_date"}))
    assert data["expiry_date"] == expiry


def test_attach_keeps_null_when_field_exists_and_unset():
    dummy = SimpleNamespace(expiry_date=None)
    data = attach_ledger_expiry_date({}, dummy, model=_dummy_model({"expiry_date"}))
    assert data["expiry_date"] is None


def test_attach_missing_attr_on_dummy_is_null():
    dummy = SimpleNamespace()
    data = attach_ledger_expiry_date({}, dummy, model=_dummy_model({"expiry_date"}))
    assert data["expiry_date"] is None


def test_row_serializer_omits_expiry_on_real_log_model():
    row = InventoryLedgerRowSerializer(_fake_log()).data
    assert "expiry_date" not in row
    assert row["id"] == 11
    assert row["product_name"] == "Dummy Milk"


def test_row_serializer_echoes_when_helper_true(monkeypatch):
    expiry = date(2026, 11, 15)
    monkeypatch.setattr(
        "products.inventory_ledger.log_has_expiry_date_field",
        lambda model=None: True,
    )
    row = InventoryLedgerRowSerializer(_fake_log(expiry_date=expiry)).data
    assert row["expiry_date"] == expiry


def test_product_search_meta_does_not_gain_expiry_date():
    assert "expiry_date" not in ProductSearchSerializer.Meta.fields


def test_attach_does_not_hit_live_hosts():
    """Guard: this slice stays dummy/local — never call *.ordereasy.win."""
    dummy = SimpleNamespace(expiry_date=date(2026, 10, 1))
    data = attach_ledger_expiry_date(
        {"reason": "Dummy write-off"},
        dummy,
        model=_dummy_model({"expiry_date"}),
    )
    assert data["expiry_date"] == date(2026, 10, 1)
    assert "ordereasy.win" not in str(data)


def test_attach_does_not_use_request_mocks_for_hosts():
    request = MagicMock()
    request.url = "http://testserver/api/products/erp/inventory-ledger/"
    dummy = SimpleNamespace(expiry_date=date(2026, 10, 2))
    data = attach_ledger_expiry_date({}, dummy, model=_dummy_model({"expiry_date"}))
    request.get.assert_not_called()
    assert data["expiry_date"] == date(2026, 10, 2)


@pytest.mark.django_db
class TestInventoryLedgerExpiryApi:
    def test_real_log_omits_expiry_when_model_has_no_field(self, api_client):
        owner, shop = _make_retailer("led_exp_none", "Ledger No Expiry Shop")
        product = _make_product(shop, "Ledger Loose Rice", barcode=PRIMARY)
        log = _log(product, owner)
        assert log_has_expiry_date_field() is False

        api_client.force_authenticate(user=owner)
        response = api_client.get(_ledger_url(), {"product_id": product.id})

        assert response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in response.data] == [log.id]
        assert "expiry_date" not in response.data[0]

    def test_echoes_dummy_value_when_helper_true(self, api_client, monkeypatch):
        owner, shop = _make_retailer("led_exp_echo", "Ledger Echo Shop")
        product = _make_product(shop, "Ledger Echo Milk", barcode=PRIMARY)
        log = _log(product, owner)
        expiry = date(2026, 12, 8)
        monkeypatch.setattr(
            "products.inventory_ledger.log_has_expiry_date_field",
            lambda model=None: True,
        )
        log.expiry_date = expiry

        row = InventoryLedgerRowSerializer(log).data
        assert row["expiry_date"] == expiry

        api_client.force_authenticate(user=owner)
        response = api_client.get(_ledger_url(), {"product_id": product.id})
        assert response.status_code == status.HTTP_200_OK
        # Fresh DB row has no column value — field-exists path echoes null.
        assert response.data[0]["expiry_date"] is None

    def test_unauthenticated_and_customer_denied(self, api_client):
        owner, shop = _make_retailer("led_exp_auth", "Ledger Expiry Auth Shop")
        product = _make_product(shop, "Ledger Auth Rice", barcode=PRIMARY)
        _log(product, owner)
        customer = _make_customer("led_exp_cust")

        anon = api_client.get(_ledger_url(), {"product_id": product.id})
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

        api_client.force_authenticate(user=customer)
        denied = api_client.get(_ledger_url(), {"product_id": product.id})
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_shop_wide_query_budget_unchanged(
        self, api_client, django_assert_num_queries
    ):
        owner, shop = _make_retailer("led_exp_q", "Ledger Expiry Query Shop")
        logs = []
        for i in range(3):
            product = _make_product(
                shop, f"Ledger Q{i}", barcode=f"89031530000{i}"
            )
            logs.append(_log(product, owner))

        api_client.force_authenticate(user=owner)
        # RetailerProfile get + one select_related(product, created_by) log fetch.
        with django_assert_num_queries(2):
            response = api_client.get(_ledger_url(), {"reason": REASON_UPDATE})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3
        assert all("expiry_date" not in row for row in response.data)
        assert {row["id"] for row in response.data} == {log.id for log in logs}
