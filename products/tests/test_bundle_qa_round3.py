"""Regressions found in the third QA round on the catalog-field bundle (RCP #186)."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from orders.models import Order, OrderItem
from products.models import Product, ProductBatch, shop_today
from products.tests.test_catalog_margin_percent_oe169 import (
    _make_location_profile,
    _make_staff,
)
from retailers.organization import ensure_organization_for_profile


def _rows(response):
    data = response.data
    return data.get("results", data) if isinstance(data, dict) else data


def _ids(response):
    return {row["id"] for row in _rows(response)}


def _batch_product(retailer, name, expiry_offset_days, quantity="4", **extra):
    product = Product.objects.create(
        retailer=retailer, name=name, price=Decimal("40.00"), quantity=Decimal(quantity),
        has_batches=True, track_inventory=True, **extra,
    )
    ProductBatch.objects.create(
        product=product, retailer=retailer, batch_number=f"{name}-B1", price=Decimal("40.00"),
        purchase_price=Decimal("31.00"), quantity=Decimal(quantity),
        expiry_date=shop_today() + timedelta(days=expiry_offset_days),
    )
    return product


def _pack_child(parent, name, conversion_factor="0.04"):
    child = Product.objects.create(
        retailer=parent.retailer, name=name, price=Decimal("65.00"), quantity=Decimal("0"),
        track_inventory=True, parent_bulk_product=parent,
        conversion_factor=Decimal(conversion_factor), unit="pack",
    )
    child.refresh_from_db()
    return child


@pytest.mark.django_db
class TestCashierCatalogHidesBatchCost:
    def _cashier_with_batch_product(self, retailer):
        org = ensure_organization_for_profile(retailer)
        cashier = _make_staff(org, "qa3_cashier", ["orders.create", "orders.read"])
        loc = _make_location_profile(cashier, org, "QA3 Counter")
        product = _batch_product(loc, "Milk", 4, purchase_price=Decimal("44.00"))
        return cashier, product

    def test_cashier_list_and_search_omit_batch_purchase_price(self, api_client, retailer):
        cashier, product = self._cashier_with_batch_product(retailer)
        api_client.force_authenticate(user=cashier)
        for resp in (
            api_client.get("/api/products/", {"page_size": 50}),
            api_client.get("/api/products/"),
            api_client.get("/api/products/search/", {"search": "milk"}),
        ):
            assert resp.status_code == 200
            row = next(r for r in _rows(resp) if r["id"] == product.id)
            assert "purchase_price" not in row
            assert row["batches"], "batch rows are still listed for the till"
            for batch in row["batches"]:
                assert "purchase_price" not in batch
                assert batch["batch_number"] == "Milk-B1"

    def test_owner_list_keeps_batch_purchase_price(self, api_client, retailer, retailer_user):
        product = _batch_product(retailer, "Milk", 4)
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.get("/api/products/", {"page_size": 50})
        row = next(r for r in _rows(resp) if r["id"] == product.id)
        assert Decimal(str(row["batches"][0]["purchase_price"])) == Decimal("31.00")


@pytest.mark.django_db
class TestPackChildFollowsParentExpiry:
    def test_child_of_expired_only_parent_is_hidden_from_customer(self, api_client, retailer, customer):
        expired_parent = _batch_product(retailer, "Rice 25kg", -3, quantity="2", is_parent_bulk=True)
        hidden_child = _pack_child(expired_parent, "Rice 1kg")
        fresh_parent = _batch_product(retailer, "Dal 25kg", 30, quantity="2", is_parent_bulk=True)
        visible_child = _pack_child(fresh_parent, "Dal 1kg")
        assert hidden_child.quantity > 0, "child stock mirrors the parent's on-hand"

        api_client.force_authenticate(user=customer)
        listed = _ids(api_client.get(f"/api/products/retailer/{retailer.id}/"))
        assert visible_child.id in listed
        assert hidden_child.id not in listed
        assert expired_parent.id not in listed

        found = _ids(api_client.get(f"/api/products/retailer/{retailer.id}/search/", {"search": "rice"}))
        assert hidden_child.id not in found

    def test_child_of_plain_tracked_parent_stays_visible(self, api_client, retailer, customer):
        parent = Product.objects.create(
            retailer=retailer, name="Sugar 50kg", price=Decimal("2000"), quantity=Decimal("1"),
            track_inventory=True, is_parent_bulk=True,
        )
        child = _pack_child(parent, "Sugar 1kg", conversion_factor="0.02")
        api_client.force_authenticate(user=customer)
        assert child.id in _ids(api_client.get(f"/api/products/retailer/{retailer.id}/"))

    def test_retailer_still_sees_the_child(self, api_client, retailer, retailer_user):
        expired_parent = _batch_product(retailer, "Rice 25kg", -3, quantity="2", is_parent_bulk=True)
        child = _pack_child(expired_parent, "Rice 1kg")
        api_client.force_authenticate(user=retailer_user)
        assert child.id in _ids(api_client.get("/api/products/", {"page_size": 50}))


@pytest.mark.django_db
class TestCustomerDetailShowsSaleableStock:
    def _detail(self, api_client, retailer, product):
        resp = api_client.get(f"/api/products/retailer/{retailer.id}/{product.id}/")
        assert resp.status_code == 200
        return resp.data

    def test_expired_only_product_reads_out_of_stock(self, api_client, retailer, customer):
        product = _batch_product(retailer, "Curd", -2)
        api_client.force_authenticate(user=customer)
        data = self._detail(api_client, retailer, product)
        assert data["quantity"] == 0
        assert data["is_in_stock"] is False

    def test_partly_expired_product_shows_only_unexpired_units(self, api_client, retailer, customer):
        product = _batch_product(retailer, "Paneer", 5, quantity="3")
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number="Paneer-OLD", price=Decimal("40.00"),
            quantity=Decimal("2"), expiry_date=shop_today() - timedelta(days=1),
        )
        Product.objects.filter(pk=product.pk).update(quantity=Decimal("5"))
        data = self._detail(api_client, retailer, product)
        assert data["quantity"] == 3
        assert data["is_in_stock"] is True

    def test_child_of_expired_only_parent_reads_out_of_stock(self, api_client, retailer, customer):
        parent = _batch_product(retailer, "Rice 25kg", -3, quantity="2", is_parent_bulk=True)
        child = _pack_child(parent, "Rice 1kg")
        data = self._detail(api_client, retailer, child)
        assert data["quantity"] == 0
        assert data["is_in_stock"] is False

    def test_plain_and_untracked_products_are_unchanged(self, api_client, retailer, customer):
        plain = Product.objects.create(
            retailer=retailer, name="Soap", price=Decimal("30"), quantity=Decimal("7"),
        )
        untracked = Product.objects.create(
            retailer=retailer, name="Tea", price=Decimal("10"), quantity=Decimal("0"),
            track_inventory=False,
        )
        assert self._detail(api_client, retailer, plain)["quantity"] == 7
        data = self._detail(api_client, retailer, untracked)
        assert data["quantity"] == 0
        assert data["is_in_stock"] is True


@pytest.mark.django_db
class TestErpListsForNonShopUsers:
    @pytest.mark.parametrize("url", [
        "/api/products/erp/purchase-invoices/",
        "/api/products/erp/supplier-ledger/",
    ])
    def test_customer_gets_404_not_500(self, api_client, customer, url):
        api_client.force_authenticate(user=customer)
        assert api_client.get(url).status_code == 404
        assert api_client.post(url, {}, format="json").status_code in (400, 404)

    def test_owner_still_lists_invoices(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        assert api_client.get("/api/products/erp/purchase-invoices/").status_code == 200
        assert api_client.get("/api/products/erp/supplier-ledger/").status_code == 200


@pytest.mark.django_db
class TestReturnsCannotBeEditedOrDeleted:
    def test_sales_return_rejects_patch_put_delete(self, api_client, retailer, retailer_user, customer):
        from retailers.tests.test_staff_roles import _make_retailer
        from returns.models import SalesReturn

        _other_user, other = _make_retailer("qa3_other", "Other Shop")
        other_order = Order.objects.create(
            customer=customer, retailer=other, source="app", status="delivered",
            subtotal=Decimal("500"), total_amount=Decimal("500"), payment_mode="cash",
            delivery_mode="pickup",
        )
        mine = SalesReturn.objects.create(
            retailer=retailer, refund_amount=Decimal("90"), refund_payment_mode="cash", notes="ok",
        )
        api_client.force_authenticate(user=retailer_user)
        url = f"/api/returns/sales/{mine.id}/"
        payload = {"order": other_order.id, "notes": "x" * 5000}
        assert api_client.patch(url, payload, format="json").status_code == 405
        assert api_client.put(url, payload, format="json").status_code == 405
        assert api_client.delete(url).status_code == 405

        mine.refresh_from_db()
        assert mine.order_id is None
        assert mine.notes == "ok"
        assert api_client.get(url).status_code == 200
        assert api_client.get("/api/returns/sales/").status_code == 200

    def test_purchase_return_rejects_patch_delete(self, api_client, retailer, retailer_user):
        from retailers.models import Supplier
        from returns.models import PurchaseReturn

        supplier = Supplier.objects.create(retailer=retailer, company_name="Agro")
        pr = PurchaseReturn.objects.create(
            retailer=retailer, supplier=supplier, total_amount=Decimal("100"), notes="ok",
        )
        api_client.force_authenticate(user=retailer_user)
        url = f"/api/returns/purchase/{pr.id}/"
        assert api_client.patch(url, {"notes": "changed"}, format="json").status_code == 405
        assert api_client.delete(url).status_code == 405
        pr.refresh_from_db()
        assert pr.notes == "ok"
        assert api_client.get(url).status_code == 200


@pytest.mark.django_db
class TestOrderModificationResponses:
    @pytest.fixture(autouse=True)
    def _no_notifications(self):
        # Status changes notify on background threads; keep them out of the test DB.
        with patch("common.notification_dispatcher.dispatch_order_status_notification"), \
                patch("common.notifications.send_push_notification"), \
                patch("common.notifications.send_silent_update"):
            yield

    def _order(self, customer, retailer, product, status):
        order = Order.objects.create(
            customer=customer, retailer=retailer, source="app", status=status,
            subtotal=Decimal("90"), total_amount=Decimal("90"), payment_mode="cash",
            delivery_mode="pickup", notes="Call before", pickup_code="482913",
        )
        item = OrderItem.objects.create(
            order=order, product=product, product_name=product.name,
            product_price=product.price, quantity=1, unit_price=product.price,
            total_price=product.price,
        )
        return order, item

    def test_staff_modify_response_keeps_notes_without_pickup_code(
        self, api_client, retailer, retailer_user, customer, product
    ):
        order, item = self._order(customer, retailer, product, "pending")
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post(
            f"/api/orders/{order.id}/modify/", {"items": [{"id": item.id, "quantity": 2}]}, format="json"
        )
        assert resp.status_code == 200, resp.data
        assert resp.data["notes"] == "Call before"
        assert "pickup_code" not in resp.data

    def test_item_added_to_app_order_is_priced_at_the_app_price(
        self, api_client, retailer, retailer_user, customer, product
    ):
        order, _item = self._order(customer, retailer, product, "pending")
        ghee = Product.objects.create(
            retailer=retailer, name="Ghee", price=Decimal("40.00"), app_price=Decimal("45.00"),
            quantity=Decimal("10"),
        )
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post(
            f"/api/orders/{order.id}/modify/",
            {"items": [{"product_id": ghee.id, "quantity": 2}]},
            format="json",
        )
        assert resp.status_code == 200, resp.data
        line = OrderItem.objects.get(order=order, product=ghee)
        assert line.unit_price == Decimal("45.00")
        assert line.product_price == Decimal("45.00")
        assert line.total_price == Decimal("90.00")

    def test_customer_confirm_response_has_pickup_code_without_notes(
        self, api_client, retailer, customer, product
    ):
        order, _item = self._order(customer, retailer, product, "waiting_for_customer_approval")
        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            f"/api/orders/{order.id}/confirm_modification/", {"action": "accept"}, format="json"
        )
        assert resp.status_code == 200, resp.data
        assert resp.data["pickup_code"] == "482913"
        assert "notes" not in resp.data


@pytest.mark.django_db
class TestFrequentlyBoughtSkipsHiddenCoPurchases:
    def test_out_of_stock_co_purchases_do_not_crowd_out_sellable_ones(
        self, api_client, retailer, customer
    ):
        from products.frequently_bought import FBT_LIMIT

        seed = Product.objects.create(retailer=retailer, name="Bread", price=Decimal("40"), quantity=9)
        hidden = [
            Product.objects.create(retailer=retailer, name=f"Gone {n}", price=Decimal("5"), quantity=0)
            for n in range(FBT_LIMIT)
        ]
        sellable = Product.objects.create(retailer=retailer, name="Butter", price=Decimal("55"), quantity=6)
        for n in range(3):
            order = Order.objects.create(
                customer=customer, retailer=retailer, source="app", status="delivered",
                subtotal=Decimal("100"), total_amount=Decimal("100"), payment_mode="cash",
                delivery_mode="pickup",
            )
            # The hidden products are bought with the seed more often than the sellable one.
            lines = [seed, *hidden] + ([sellable] if n == 0 else [])
            for line_product in lines:
                OrderItem.objects.create(
                    order=order, product=line_product, product_name=line_product.name,
                    product_price=line_product.price, quantity=1,
                    unit_price=line_product.price, total_price=line_product.price,
                )

        resp = api_client.get(
            f"/api/products/retailer/{retailer.id}/frequently-bought-together/",
            {"product_ids": seed.id},
        )
        assert resp.status_code == 200
        ids = [row["id"] for row in resp.data]
        assert sellable.id in ids
        assert not set(ids) & {p.id for p in hidden}


def _public_catalog_urls(shop, product):
    base = f"/api/products/retailer/{shop.id}"
    return [
        f"{base}/",
        f"{base}/search/?search=rice",
        f"{base}/featured/",
        f"{base}/best-selling/",
        f"{base}/recommended/",
        f"{base}/deals-of-the-day/",
        f"{base}/budget-buys/",
        f"{base}/trending-now/",
        f"{base}/new-arrivals/",
        f"{base}/seasonal-picks/",
        f"{base}/{product.id}/",
        f"{base}/frequently-bought-together/?product_ids={product.id}",
    ]


@pytest.mark.django_db
class TestPublicCatalogNeverShowsCost:
    def _shop_with_costly_product(self, retailer):
        product = _batch_product(
            retailer, "Basmati Rice", 30, purchase_price=Decimal("777.77"), is_featured=True,
            original_price=Decimal("60.00"), is_seasonal=True, product_group="rice",
        )
        Product.objects.filter(pk=product.pk).update(app_price=Decimal("45.00"))
        ProductBatch.objects.filter(product=product).update(purchase_price=Decimal("777.77"))
        sibling = Product.objects.create(
            retailer=retailer, name="Sona Rice", price=Decimal("50"), quantity=Decimal("3"),
            product_group="rice",
        )
        order = Order.objects.create(
            retailer=retailer, source="app", status="delivered", subtotal=Decimal("90"),
            total_amount=Decimal("90"), payment_mode="cash", delivery_mode="pickup",
        )
        for line in (product, sibling):
            OrderItem.objects.create(
                order=order, product=line, product_name=line.name, product_price=line.price,
                quantity=1, unit_price=line.price, total_price=line.price,
            )
        product.refresh_from_db()
        return product

    def _assert_no_cost(self, api_client, shop, product):
        for url in _public_catalog_urls(shop, product):
            resp = api_client.get(url)
            assert resp.status_code == 200, (url, resp.status_code)
            body = resp.content.decode()
            assert "777.77" not in body, url
            assert "purchase_price" not in body, url
            assert '"app_price"' not in body, url

    def test_another_shops_owner_gets_app_prices_and_no_cost(self, api_client, retailer):
        from retailers.tests.test_staff_roles import _make_retailer

        product = self._shop_with_costly_product(retailer)
        rival_user, _rival = _make_retailer("qa3_rival", "Rival Shop")
        api_client.force_authenticate(user=rival_user)
        self._assert_no_cost(api_client, retailer, product)
        detail = api_client.get(f"/api/products/retailer/{retailer.id}/{product.id}/")
        assert Decimal(str(detail.data["price"])) == Decimal("45.00")

    def test_own_cashier_gets_no_cost_on_the_public_catalog(self, api_client, retailer):
        org = ensure_organization_for_profile(retailer)
        cashier = _make_staff(org, "qa3_pub_cashier", ["orders.create", "orders.read"])
        _make_location_profile(cashier, org, "QA3 Pub Counter")
        product = self._shop_with_costly_product(retailer)
        api_client.force_authenticate(user=cashier)
        self._assert_no_cost(api_client, retailer, product)

    def test_owner_still_gets_store_price_and_cost_on_shop_endpoints(self, api_client, retailer, retailer_user):
        product = self._shop_with_costly_product(retailer)
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.get(f"/api/products/{product.id}/")
        assert resp.status_code == 200
        assert Decimal(str(resp.data["price"])) == Decimal("40.00")
        assert Decimal(str(resp.data["app_price"])) == Decimal("45.00")
        assert Decimal(str(resp.data["purchase_price"])) == Decimal("777.77")


@pytest.mark.django_db
class TestDiscountFollowsTheChannelPrice:
    """Store 270, app 280, MRP 300: the app shows 6.67% / Rs 20 off, the shop 10% / Rs 30."""

    def _atta(self, retailer, app_price="280.00"):
        product = Product.objects.create(
            retailer=retailer, name="Atta 5kg", price=Decimal("270.00"), original_price=Decimal("300.00"),
            quantity=Decimal("10"), track_inventory=True, is_featured=True,
        )
        Product.objects.filter(pk=product.pk).update(app_price=Decimal(app_price))
        product.refresh_from_db()
        return product

    def test_customer_detail_and_lists_use_the_app_price(self, api_client, retailer, customer):
        product = self._atta(retailer)
        api_client.force_authenticate(user=customer)
        base = f"/api/products/retailer/{retailer.id}"
        detail = api_client.get(f"{base}/{product.id}/").data
        assert Decimal(str(detail["price"])) == Decimal("280.00")
        assert Decimal(str(detail["discount_percentage"])) == Decimal("6.67")
        assert Decimal(str(detail["savings"])) == Decimal("20.00")
        for url in (f"{base}/", f"{base}/featured/"):
            row = next(r for r in _rows(api_client.get(url)) if r["id"] == product.id)
            assert Decimal(str(row["discount_percentage"])) == Decimal("6.67"), url

    def test_app_price_at_or_above_mrp_shows_no_discount(self, api_client, retailer, customer):
        product = self._atta(retailer, app_price="310.00")
        api_client.force_authenticate(user=customer)
        detail = api_client.get(f"/api/products/retailer/{retailer.id}/{product.id}/").data
        assert Decimal(str(detail["discount_percentage"])) == Decimal("0")
        assert Decimal(str(detail["savings"])) == Decimal("0")

    def test_shop_detail_keeps_the_store_discount(self, api_client, retailer, retailer_user):
        product = self._atta(retailer)
        api_client.force_authenticate(user=retailer_user)
        detail = api_client.get(f"/api/products/{product.id}/").data
        assert Decimal(str(detail["price"])) == Decimal("270.00")
        assert Decimal(str(detail["discount_percentage"])) == Decimal("10.00")
        assert Decimal(str(detail["savings"])) == Decimal("30.00")


MISSING = 999999


@pytest.mark.django_db
class TestMissingObjectsAre404Not500:
    @pytest.fixture(autouse=True)
    def _no_notifications(self):
        with patch("common.notifications.send_push_notification"), \
                patch("common.notifications.send_silent_update"):
            yield

    @pytest.mark.parametrize("method,url", [
        ("put", f"/api/cart/items/{MISSING}/"),
        ("delete", f"/api/cart/items/{MISSING}/remove/"),
        ("get", f"/api/customer/addresses/{MISSING}/"),
        ("patch", f"/api/customer/addresses/{MISSING}/update/"),
        ("delete", f"/api/customer/addresses/{MISSING}/delete/"),
        ("patch", f"/api/customer/notifications/{MISSING}/read/"),
        ("delete", f"/api/customer/wishlist/remove/{MISSING}/"),
        ("post", f"/api/orders/{MISSING}/cancel/"),
        ("post", f"/api/orders/{MISSING}/chat/send/"),
        ("post", f"/api/orders/{MISSING}/confirm_modification/"),
        ("post", f"/api/orders/{MISSING}/feedback/"),
        ("post", f"/api/orders/{MISSING}/return/"),
        ("post", f"/api/orders/{MISSING}/submit_payment/"),
        ("patch", f"/api/orders/{MISSING}/fulfillment-slot/"),
    ])
    def test_customer(self, api_client, customer, method, url):
        api_client.force_authenticate(user=customer)
        assert getattr(api_client, method)(url, {}, format="json").status_code == 404

    @pytest.mark.parametrize("method,url", [
        ("get", f"/api/customer/retailer/details/{MISSING}/"),
        ("get", f"/api/customer/retailer/ledger/{MISSING}/"),
        ("patch", f"/api/customer/retailer/update/{MISSING}/"),
        ("delete", f"/api/products/{MISSING}/delete/"),
    ])
    def test_shop_owner(self, api_client, retailer, retailer_user, method, url):
        api_client.force_authenticate(user=retailer_user)
        assert getattr(api_client, method)(url, {}, format="json").status_code == 404

    def test_staff_without_a_shop_profile(self, api_client, retailer, category):
        org = ensure_organization_for_profile(retailer)
        staff = _make_staff(org, "qa3_noprof", ["orders.read"])
        api_client.force_authenticate(user=staff)
        for method, url in (
            ("get", "/api/customer/retailer/list/"),
            ("get", "/api/customer/loyalty/retailer-customers/"),
            ("patch", f"/api/products/categories/{category.id}/update/"),
            ("delete", f"/api/products/categories/{category.id}/delete/"),
            ("get", "/api/retailer/reward-config/"),
        ):
            resp = getattr(api_client, method)(url, {}, format="json")
            assert resp.status_code == 404, (url, resp.status_code)


@pytest.mark.django_db
def test_models_and_migrations_are_in_sync(settings):
    """The bundle once shipped model changes without migrations; makemigrations must stay clean."""
    from io import StringIO

    from django.core.management import call_command

    # --nomigrations hides every migration module, which would make this check pass vacuously.
    settings.MIGRATION_MODULES = {}
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=StringIO())
    except SystemExit as exc:
        pytest.fail(f"missing migrations (exit {exc.code}):\n{out.getvalue()}")
