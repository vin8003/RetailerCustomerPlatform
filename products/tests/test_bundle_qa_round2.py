"""Regressions found in the second QA round on the catalog-field bundle (RCP #186)."""
from datetime import timedelta
from decimal import Decimal

import pytest

from products.models import Product, ProductBatch, shop_today
from products.tests.test_catalog_margin_percent_oe169 import (
    _make_location_profile,
    _make_staff,
)
from retailers.organization import ensure_organization_for_profile


def _batch_product(retailer, name, expiry_offset_days):
    product = Product.objects.create(
        retailer=retailer, name=name, price=Decimal("40.00"), quantity=Decimal("4"),
        has_batches=True, track_inventory=True,
    )
    ProductBatch.objects.create(
        product=product, retailer=retailer, batch_number=f"{name}-B1", price=Decimal("40.00"),
        quantity=Decimal("4"), expiry_date=shop_today() + timedelta(days=expiry_offset_days),
    )
    return product


def _ids(response):
    data = response.data
    rows = data.get("results", data) if isinstance(data, dict) else data
    return {row["id"] for row in rows}


@pytest.mark.django_db
class TestCustomerHidesExpiredOnlyStock:
    def test_expired_only_batch_product_is_hidden_from_customer_list_and_search(
        self, api_client, retailer, customer
    ):
        expired = _batch_product(retailer, "Curd", -2)
        fresh = _batch_product(retailer, "Paneer", 5)
        api_client.force_authenticate(user=customer)

        listed = _ids(api_client.get(f"/api/products/retailer/{retailer.id}/"))
        assert fresh.id in listed
        assert expired.id not in listed

        found = _ids(api_client.get(f"/api/products/retailer/{retailer.id}/search/", {"search": "curd"}))
        assert expired.id not in found

    def test_batch_expiring_today_still_counts(self, api_client, retailer, customer):
        today = _batch_product(retailer, "Bread", 0)
        api_client.force_authenticate(user=customer)
        assert today.id in _ids(api_client.get(f"/api/products/retailer/{retailer.id}/"))

    def test_retailer_still_sees_expired_only_product(self, api_client, retailer, retailer_user):
        expired = _batch_product(retailer, "Curd", -2)
        api_client.force_authenticate(user=retailer_user)
        assert expired.id in _ids(api_client.get("/api/products/", {"page_size": 50}))


@pytest.mark.django_db
class TestCashierCatalogHidesCost:
    def _cashier_with_product(self, retailer):
        org = ensure_organization_for_profile(retailer)
        cashier = _make_staff(org, "qa2_cashier", ["orders.create", "orders.read"])
        loc = _make_location_profile(cashier, org, "QA2 Counter")
        product = Product.objects.create(
            retailer=loc, name="Atta", price=Decimal("270.00"), purchase_price=Decimal("220.00"),
            quantity=Decimal("5"),
        )
        return cashier, product

    def test_cashier_list_and_search_omit_purchase_price(self, api_client, retailer):
        cashier, product = self._cashier_with_product(retailer)
        api_client.force_authenticate(user=cashier)
        for resp in (
            api_client.get("/api/products/", {"page_size": 50}),
            api_client.get("/api/products/"),
            api_client.get("/api/products/search/", {"search": "atta"}),
        ):
            assert resp.status_code == 200
            rows = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
            row = next(r for r in rows if r["id"] == product.id)
            assert "purchase_price" not in row
            assert "margin_percent" not in row

    def test_owner_list_keeps_purchase_price(self, api_client, retailer, retailer_user, product):
        Product.objects.filter(pk=product.pk).update(purchase_price=Decimal("80.00"))
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.get("/api/products/", {"page_size": 50})
        row = next(r for r in resp.data["results"] if r["id"] == product.id)
        assert Decimal(str(row["purchase_price"])) == Decimal("80.00")


@pytest.mark.django_db
class TestNoServerErrors:
    def test_pos_with_another_shops_product_is_400(self, api_client, retailer_user, retailer):
        from retailers.tests.test_staff_roles import _make_retailer
        _other_user, other = _make_retailer("qa2_other", "Other")
        foreign = Product.objects.create(retailer=other, name="Foreign", price=Decimal("10"), quantity=5)
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post(
            "/api/products/erp/pos-checkout/",
            {"items": [{"product_id": foreign.id, "quantity": 1, "unit_price": 10}],
             "subtotal": 10, "total_amount": 10, "payment_details": {"cash": 10}},
            format="json",
        )
        assert resp.status_code == 400
        foreign.refresh_from_db()
        assert foreign.quantity == 5

    def test_customer_on_sales_returns_api_is_404(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        assert api_client.get("/api/returns/sales/").status_code == 404
        assert api_client.get("/api/returns/sales/1/").status_code == 404
        assert api_client.get("/api/returns/sales/search_order/", {"query": "x"}).status_code == 404


@pytest.mark.django_db
class TestStatsWithFullyReturnedOrder:
    def test_fully_returned_online_order_nets_to_zero_not_negative(self, api_client, retailer_user, retailer, customer):
        from orders.models import Order
        from returns.models import SalesReturn

        Order.objects.create(
            customer=customer, retailer=retailer, source="pos", status="delivered",
            subtotal=Decimal("300.00"), total_amount=Decimal("300.00"), payment_mode="cash",
            cash_amount=Decimal("300.00"), delivery_mode="pickup",
        )
        returned = Order.objects.create(
            customer=customer, retailer=retailer, source="app", status="returned",
            subtotal=Decimal("525.00"), total_amount=Decimal("525.00"), payment_mode="cash",
            delivery_mode="delivery",
        )
        SalesReturn.objects.create(
            retailer=retailer, order=returned, refund_amount=Decimal("525.00"), refund_payment_mode="cash",
        )
        api_client.force_authenticate(user=retailer_user)
        data = api_client.get("/api/orders/stats/").data
        assert Decimal(str(data["online_sales"])) == 0
        assert Decimal(str(data["pos_sales"])) == 300
        assert Decimal(str(data["total_revenue"])) == 300
