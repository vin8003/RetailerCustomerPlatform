"""Bad input found by the third QA round's endpoint sweep (RCP #186).

Each case used to answer 500, or (POS, returns) record a sale or return built from a negative
or empty line. A client mistake is a 400 that names the field, or a 404 for an id that is not
there; nothing is written.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from orders.models import Order, OrderItem
from products.models import (
    Product,
    ProductBatch,
    ProductInventoryLog,
    PurchaseInvoice,
    PurchaseItem,
    SupplierLedger,
    shop_today,
)
from retailers.models import RetailerCustomerMapping, Supplier
from retailers.organization import ensure_organization_for_profile
from returns.models import PurchaseReturn, SalesReturn

POS_URL = "/api/products/erp/pos-checkout/"


def _line(product, quantity=1, **extra):
    return {"product_id": product.id, "quantity": quantity, "unit_price": str(product.price), **extra}


def _pos(api_client, user, items, **extra):
    api_client.force_authenticate(user=user)
    return api_client.post(POS_URL, {"payment_mode": "cash", "items": items, **extra}, format="json")


def _batched(retailer, name, *lots):
    """Product with (batch_number, quantity, days_to_expiry) lots."""
    product = Product.objects.create(
        retailer=retailer, name=name, price=Decimal("40.00"), has_batches=True, track_inventory=True,
    )
    batches = [
        ProductBatch.objects.create(
            product=product, retailer=retailer, batch_number=number, price=Decimal("40.00"),
            quantity=Decimal(quantity), expiry_date=shop_today() + timedelta(days=days),
        )
        for number, quantity, days in lots
    ]
    product.sync_inventory_from_batches()
    return product, batches


@pytest.mark.django_db
class TestPosRefusesBadLines:
    @pytest.mark.parametrize("quantity", [-3, 0, "-0.5"])
    def test_quantity_must_be_above_zero(self, api_client, retailer_user, product, quantity):
        resp = _pos(api_client, retailer_user, [_line(product, quantity)])
        assert resp.status_code == 400
        assert resp.data["error"].startswith("quantity:")
        product.refresh_from_db()
        assert product.quantity == 50
        assert not Order.objects.filter(source="pos").exists()

    @pytest.mark.parametrize("items", [
        "x",
        [1, 2],
        [{"product_id": "abc", "quantity": 1, "unit_price": "90.00"}],
    ], ids=["text", "numbers", "product_id_text"])
    def test_malformed_items(self, api_client, retailer_user, product, items):
        resp = _pos(api_client, retailer_user, items)
        assert resp.status_code == 400
        assert not Order.objects.filter(source="pos").exists()

    @pytest.mark.parametrize("change", [
        {"quantity": "x"},
        {"unit_price": "abc"},
        {"unit_price": None},
        {"batch_id": "abc"},
    ], ids=["quantity_text", "price_text", "price_missing", "batch_text"])
    def test_malformed_line_fields(self, api_client, retailer_user, product, change):
        resp = _pos(api_client, retailer_user, [{**_line(product), **change}])
        assert resp.status_code == 400
        assert not Order.objects.filter(source="pos").exists()

    @pytest.mark.parametrize("extra", [
        {"discount_amount": "abc"},
        {"discount_amount": "-10"},
        {"payment_mode": "split", "payment_details": {"cash": "abc"}},
    ], ids=["discount_text", "discount_negative", "payment_text"])
    def test_malformed_bill_fields(self, api_client, retailer_user, product, extra):
        resp = _pos(api_client, retailer_user, [_line(product)], **extra)
        assert resp.status_code == 400
        assert not Order.objects.filter(source="pos").exists()

    def test_discount_is_capped_at_the_bill(self, api_client, retailer_user, product):
        resp = _pos(api_client, retailer_user, [_line(product)], discount_amount="500")
        assert resp.status_code == 201, resp.data
        order = Order.objects.get(source="pos")
        assert order.subtotal == Decimal("90.00")
        assert order.discount_amount == Decimal("90.00")
        assert order.total_amount == Decimal("0.00")

    def test_expired_batch_is_refused_with_the_reason(self, api_client, retailer_user, retailer):
        product, (expired,) = _batched(retailer, "Curd", ("CURD-OLD", "6", -1))
        resp = _pos(api_client, retailer_user, [_line(product, 1, batch_id=expired.id)])
        assert resp.status_code == 400
        assert resp.data["error"] == "Batch CURD-OLD of Curd has expired and cannot be sold"
        expired.refresh_from_db()
        assert expired.quantity == Decimal("6")
        assert not Order.objects.filter(source="pos").exists()

    def test_short_expired_batch_still_sells_from_fresh_lots(self, api_client, retailer_user, retailer):
        # Unchanged: a named lot too small for the line falls back to FIFO, which skips expired lots.
        product, (expired, fresh) = _batched(retailer, "Paneer", ("PAN-OLD", "1", -1), ("PAN-NEW", "10", 20))
        resp = _pos(api_client, retailer_user, [_line(product, 3, batch_id=expired.id)])
        assert resp.status_code == 201, resp.data
        expired.refresh_from_db()
        fresh.refresh_from_db()
        assert expired.quantity == Decimal("1")
        assert fresh.quantity == Decimal("7")


@pytest.mark.django_db
class TestReturnsRefuseBadLines:
    def _sales_return(self, api_client, user, items, **extra):
        api_client.force_authenticate(user=user)
        return api_client.post(
            "/api/returns/sales/", {"items": items, "refund_payment_mode": "cash", **extra}, format="json"
        )

    def _delivered_order(self, retailer, customer, product):
        order = Order.objects.create(
            retailer=retailer, customer=customer, source="app", status="delivered", subtotal=Decimal("180"),
            total_amount=Decimal("180"), payment_mode="cash", delivery_mode="pickup",
        )
        item = OrderItem.objects.create(
            order=order, product=product, product_name=product.name, product_price=product.price,
            quantity=2, unit_price=product.price, total_price=Decimal("180"),
        )
        return order, item

    @pytest.mark.parametrize("change", [
        {"quantity": -2},
        {"quantity": "x"},
        {"refund_unit_price": "-90"},
        {"refund_unit_price": "abc"},
        {"product_id": "abc"},
        {"batch_id": "abc"},
    ], ids=["quantity_negative", "quantity_text", "price_negative", "price_text", "product_text", "batch_text"])
    def test_bad_sales_line_returns_nothing(self, api_client, retailer_user, product, change):
        line = {"product_id": product.id, "quantity": 1, "refund_unit_price": "90.00", **change}
        resp = self._sales_return(api_client, retailer_user, [line])
        assert resp.status_code == 400
        assert not SalesReturn.objects.exists()
        product.refresh_from_db()
        assert product.quantity == 50

    @pytest.mark.parametrize("items", ["x", [1, 2]], ids=["text", "numbers"])
    def test_sales_items_must_be_objects(self, api_client, retailer, retailer_user, items):
        assert self._sales_return(api_client, retailer_user, items).status_code == 400

    def test_sales_return_with_no_complete_line_is_refused(self, api_client, retailer_user, product):
        resp = self._sales_return(api_client, retailer_user, [{"product_id": product.id, "quantity": 1}])
        assert resp.status_code == 400
        assert resp.data["error"] == "items: Each item needs product_id, quantity and refund_unit_price."
        assert not SalesReturn.objects.exists()

    def test_sales_order_id_must_be_a_number(self, api_client, retailer_user, product):
        line = {"product_id": product.id, "quantity": 1, "refund_unit_price": "90.00"}
        assert self._sales_return(api_client, retailer_user, [line], order_id="abc").status_code == 400

    def test_complete_line_is_returned_and_incomplete_one_skipped(
        self, api_client, retailer_user, retailer, customer, product
    ):
        order, item = self._delivered_order(retailer, customer, product)
        resp = self._sales_return(api_client, retailer_user, [
            {"product_id": product.id, "order_item_id": item.id, "quantity": 1, "refund_unit_price": "90.00"},
            {"product_id": product.id, "quantity": 1},
        ], order_id=order.id)
        assert resp.status_code == 201, resp.data
        sales_return = SalesReturn.objects.get()
        assert sales_return.items.count() == 1
        product.refresh_from_db()
        assert product.quantity == 51

    def _purchase_return(self, api_client, user, payload):
        api_client.force_authenticate(user=user)
        return api_client.post("/api/returns/purchase/", payload, format="json")

    @pytest.mark.parametrize("change", [
        {"supplier_id": None},
        {"supplier_id": "abc"},
        {"invoice_id": "abc"},
        {"quantity": -1},
        {"purchase_price": "-5"},
    ], ids=["no_supplier", "supplier_text", "invoice_text", "quantity_negative", "price_negative"])
    def test_bad_purchase_return_is_400(self, api_client, retailer_user, retailer, product, change):
        supplier = Supplier.objects.create(retailer=retailer, company_name="Agro")
        line = {"product_id": product.id, "quantity": 1, "purchase_price": "60.00"}
        payload = {"supplier_id": supplier.id, "items": [line]}
        for key, value in change.items():
            if key in line:
                line[key] = value
            elif value is None:
                payload.pop(key)
            else:
                payload[key] = value
        resp = self._purchase_return(api_client, retailer_user, payload)
        assert resp.status_code == 400
        assert not PurchaseReturn.objects.exists()
        product.refresh_from_db()
        assert product.quantity == 50

    def test_invoice_items_lookup_needs_a_numeric_id(self, api_client, retailer, retailer_user):
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.get("/api/returns/purchase/get_invoice_items/", {"invoice_id": "x"})
        assert resp.status_code == 400


@pytest.mark.django_db
class TestReturnsFollowTheBill:
    """The Return button on a purchase bill sends no supplier_id: the bill names the supplier."""

    def _bill(self, retailer, product, supplier_name="Agro"):
        supplier = Supplier.objects.create(retailer=retailer, company_name=supplier_name)
        invoice = PurchaseInvoice.objects.create(
            retailer=retailer, supplier=supplier, invoice_number=f"{supplier_name}-1",
            invoice_date=shop_today(), total_amount=Decimal("600.00"),
        )
        line = PurchaseItem.objects.create(
            invoice=invoice, product=product, quantity=10, purchase_price=Decimal("60.00"), total=Decimal("600.00"),
        )
        return supplier, invoice, line

    def _purchase_return(self, api_client, user, payload):
        api_client.force_authenticate(user=user)
        return api_client.post("/api/returns/purchase/", payload, format="json")

    def _bill_line(self, product, bill_line, **extra):
        return {
            "product_id": product.id, "purchase_item_id": bill_line.id, "batch_id": None,
            "quantity": 2, "purchase_price": "60.00", **extra,
        }

    def test_return_from_the_bill_goes_to_its_supplier(self, api_client, retailer, retailer_user, product):
        supplier, invoice, bill_line = self._bill(retailer, product)
        resp = self._purchase_return(api_client, retailer_user, {
            "invoice_id": invoice.id, "items": [self._bill_line(product, bill_line)], "notes": "",
        })
        assert resp.status_code == 201, resp.data
        purchase_return = PurchaseReturn.objects.get()
        assert purchase_return.supplier == supplier
        assert purchase_return.invoice == invoice
        assert SupplierLedger.objects.get(transaction_type="DEBIT").supplier == supplier
        product.refresh_from_db()
        assert product.quantity == 48

    def test_matching_supplier_id_is_still_accepted(self, api_client, retailer, retailer_user, product):
        supplier, invoice, bill_line = self._bill(retailer, product)
        resp = self._purchase_return(api_client, retailer_user, {
            "supplier_id": supplier.id, "invoice_id": invoice.id, "items": [self._bill_line(product, bill_line)],
        })
        assert resp.status_code == 201, resp.data

    def test_supplier_other_than_the_bills_is_refused(self, api_client, retailer, retailer_user, product):
        _supplier, invoice, bill_line = self._bill(retailer, product)
        other = Supplier.objects.create(retailer=retailer, company_name="Other Traders")
        resp = self._purchase_return(api_client, retailer_user, {
            "supplier_id": other.id, "invoice_id": invoice.id, "items": [self._bill_line(product, bill_line)],
        })
        assert resp.status_code == 400
        assert resp.data == {"error": "This bill is from a different supplier"}
        assert not PurchaseReturn.objects.exists()
        assert not SupplierLedger.objects.filter(supplier=other).exists()
        product.refresh_from_db()
        assert product.quantity == 50

    def test_manual_return_still_needs_a_supplier(self, api_client, retailer, retailer_user, product):
        resp = self._purchase_return(api_client, retailer_user, {
            "items": [{"product_id": product.id, "quantity": 1, "purchase_price": "60.00"}],
        })
        assert resp.status_code == 400
        assert resp.data == {"error": "supplier_id is required"}

    def test_bill_line_must_be_the_same_product(self, api_client, retailer, retailer_user, product, product2):
        _supplier, invoice, bill_line = self._bill(retailer, product)
        resp = self._purchase_return(api_client, retailer_user, {
            "invoice_id": invoice.id, "items": [self._bill_line(product2, bill_line)],
        })
        assert resp.status_code == 400
        assert resp.data == {"error": "Test Wheat Flour is not the product on that bill line"}
        assert not PurchaseReturn.objects.exists()
        product2.refresh_from_db()
        assert product2.quantity == 30

    def test_order_line_must_be_the_same_product(
        self, api_client, retailer, retailer_user, customer, product, product2
    ):
        order = Order.objects.create(
            retailer=retailer, customer=customer, source="app", status="delivered", subtotal=Decimal("90"),
            total_amount=Decimal("90"), payment_mode="cash", delivery_mode="pickup",
        )
        rice = OrderItem.objects.create(
            order=order, product=product, product_name=product.name, product_price=product.price,
            quantity=1, unit_price=product.price, total_price=product.price,
        )
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post("/api/returns/sales/", {
            "order_id": order.id, "refund_payment_mode": "cash",
            "items": [{"product_id": product2.id, "order_item_id": rice.id, "quantity": 1, "refund_unit_price": "50.00"}],
        }, format="json")
        assert resp.status_code == 400
        assert resp.data == {"error": "Test Wheat Flour is not the product on that order line"}
        assert not SalesReturn.objects.exists()
        product2.refresh_from_db()
        assert product2.quantity == 30


@pytest.mark.django_db
class TestOrderEditRefusesBadInput:
    @pytest.fixture(autouse=True)
    def _no_notifications(self):
        with patch("common.notification_dispatcher.dispatch_order_status_notification"), \
                patch("common.notifications.send_push_notification"), \
                patch("common.notifications.send_silent_update"):
            yield

    def _pending(self, customer, retailer, product):
        order = Order.objects.create(
            customer=customer, retailer=retailer, source="app", status="pending", subtotal=Decimal("90"),
            total_amount=Decimal("90"), payment_mode="cash", delivery_mode="pickup",
        )
        item = OrderItem.objects.create(
            order=order, product=product, product_name=product.name, product_price=product.price,
            quantity=1, unit_price=product.price, total_price=product.price,
        )
        return order, item

    def _modify(self, api_client, user, order, items):
        api_client.force_authenticate(user=user)
        return api_client.post(f"/api/orders/{order.id}/modify/", {"items": items}, format="json")

    @pytest.mark.parametrize("make_line", [
        lambda item, product: {"product_id": "abc", "quantity": 1},
        lambda item, product: {"product_id": product.id, "quantity": "x"},
        lambda item, product: {"id": item.id, "quantity": "x"},
        lambda item, product: {"id": item.id, "unit_price": "abc"},
        lambda item, product: {"id": item.id, "unit_price": "-5"},
        lambda item, product: {"id": "abc", "quantity": 1},
    ], ids=["new_id_text", "new_qty_text", "qty_text", "price_text", "price_negative", "id_text"])
    def test_malformed_line_is_400_and_order_unchanged(
        self, api_client, retailer, retailer_user, customer, product, product2, make_line
    ):
        order, item = self._pending(customer, retailer, product)
        resp = self._modify(api_client, retailer_user, order, [make_line(item, product2)])
        assert resp.status_code == 400
        order.refresh_from_db()
        assert order.total_amount == Decimal("90.00")
        assert list(order.items.values_list("quantity", flat=True)) == [Decimal("1.000")]
        product2.refresh_from_db()
        assert product2.quantity == 30

    def test_not_enough_stock_is_a_400_with_the_reason(self, api_client, retailer, retailer_user, customer, product):
        order, _item = self._pending(customer, retailer, product)
        ghee = Product.objects.create(retailer=retailer, name="Ghee", price=Decimal("40"), quantity=Decimal("1"))
        resp = self._modify(api_client, retailer_user, order, [{"product_id": ghee.id, "quantity": 5}])
        assert resp.status_code == 400
        assert resp.data == {"error": "Not enough stock for Ghee"}
        assert not order.items.filter(product=ghee).exists()
        order.refresh_from_db()
        assert order.status == "pending"

    def test_stock_log_records_who_edited_the_order(self, api_client, retailer, retailer_user, customer, product):
        order, _item = self._pending(customer, retailer, product)
        salt = Product.objects.create(retailer=retailer, name="Salt", price=Decimal("28"), quantity=Decimal("10"))
        resp = self._modify(api_client, retailer_user, order, [{"product_id": salt.id, "quantity": 2}])
        assert resp.status_code == 200, resp.data
        log = ProductInventoryLog.objects.get(product=salt)
        assert log.created_by == retailer_user


@pytest.mark.django_db
class TestOfferPreviewRefusesBadLines:
    URL = "/api/offers/calculate/"

    @pytest.mark.parametrize("make_payload", [
        lambda shop, product: {"items": "x"},
        lambda shop, product: {"items": [1]},
        lambda shop, product: {"items": [{"product_id": "abc", "quantity": 1, "price": 90}]},
        lambda shop, product: {"items": [{"product_id": product.id, "quantity": -1, "price": 90}]},
        lambda shop, product: {"items": [{"product_id": product.id, "quantity": 1, "price": "abc"}]},
        lambda shop, product: {"items": [{"product_id": product.id, "quantity": 1}]},
        lambda shop, product: {"retailer_id": "abc", "items": []},
    ], ids=["text", "numbers", "product_text", "quantity_negative", "price_text", "price_missing", "shop_text"])
    def test_malformed_preview_is_400(self, api_client, retailer, retailer_user, product, make_payload):
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.post(self.URL, make_payload(retailer, product), format="json")
        assert resp.status_code == 400
        assert "error" in resp.data

    def test_unknown_shop_is_404(self, api_client, retailer_user, product):
        api_client.force_authenticate(user=retailer_user)
        payload = {"retailer_id": 999999, "items": [{"product_id": product.id, "quantity": 1, "price": 90}]}
        assert api_client.post(self.URL, payload, format="json").status_code == 404

    def test_zero_quantity_while_typing_is_still_priced(self, api_client, retailer, retailer_user, product):
        api_client.force_authenticate(user=retailer_user)
        payload = {"retailer_id": retailer.id, "items": [{"product_id": product.id, "quantity": 0, "price": 90}]}
        resp = api_client.post(self.URL, payload, format="json")
        assert resp.status_code == 200
        assert Decimal(str(resp.data["total_savings"])) == Decimal("0")


@pytest.mark.django_db
class TestBadQueryParamsAre4xx:
    @pytest.fixture(autouse=True)
    def _no_notifications(self):
        with patch("common.notifications.send_push_notification"), \
                patch("common.notifications.send_silent_update"):
            yield

    @pytest.mark.parametrize("url,expected", [
        ("/api/orders/current/?page=x", 404),
        ("/api/orders/current/?page=999", 404),
        ("/api/orders/history/?page=x", 404),
        ("/api/customer/notifications/?page=x", 404),
        ("/api/customer/wishlist/?page=x", 404),
        ("/api/customer/loyalty/?retailer_id=x", 404),
        ("/api/customer/reward-configuration/?retailer_id=x", 404),
        ("/api/customer/loyalty/transactions/?retailer_id=x", 400),
        ("/api/cart/?retailer_id=x", 404),
        ("/api/cart/summary/?retailer_id=x", 404),
    ])
    def test_customer_gets(self, api_client, customer, wishlist_item, notification, url, expected):
        api_client.force_authenticate(user=customer)
        assert api_client.get(url).status_code == expected

    @pytest.mark.parametrize("path,expected", [
        ("/api/retailer/?page=x", 404),
        ("/api/retailer/{shop}/reviews/?page=x", 404),
        ("/api/products/retailer/{shop}/?page=x", 404),
        ("/api/products/retailer/{shop}/?page=999", 404),
        ("/api/products/retailer/{shop}/search/?search=rice&limit=x", 400),
        ("/api/products/retailer/{shop}/search/?search=rice&limit=-1", 400),
        ("/api/products/retailer/{shop}/budget-buys/?max_price=x", 400),
        ("/api/products/retailer/{shop}/budget-buys/?max_price=-1", 400),
        ("/api/products/retailer/{shop}/categories/?parent_id=x", 400),
        # Malformed list filters are still ignored, as before.
        ("/api/products/retailer/{shop}/?min_price=nan&max_price=inf", 200),
        ("/api/products/retailer/{shop}/?offer_id=x", 200),
        ("/api/retailer/?min_rating=nan", 200),
    ])
    def test_public_gets(self, api_client, retailer, product, path, expected):
        assert api_client.get(path.format(shop=retailer.id)).status_code == expected

    @pytest.mark.parametrize("path,expected", [
        ("/api/products/?page=x", 404),
        ("/api/products/search/?search=rice&limit=x", 400),
        ("/api/orders/retailer-reviews/?page=x", 404),
        ("/api/products/erp/purchase-invoices/?start_date=x", 400),
        ("/api/products/erp/purchase-invoices/?end_date=2026-13-01", 400),
        ("/api/products/erp/supplier-ledger/?supplier=x", 400),
        ("/api/products/erp/supplier-ledger/?end_date=x", 400),
        ("/api/products/erp/inventory-ledger/?product_id=x", 400),
        ("/api/customer/retailer/list/?page=x", 404),
        ("/api/customer/retailer/ledger/{customer}/?page=x", 404),
        ("/api/retailer/org/{org}/staff/?page=x", 404),
        ("/api/retailer/org/{org}/audit-log/?page=x", 404),
        ("/api/retailer/org/{org}/api-keys/?page=x", 404),
        ("/api/retailer/org/{org}/notifications/deliveries/?page=x", 404),
    ])
    def test_shop_owner_gets(self, api_client, retailer, retailer_user, customer, product, path, expected):
        org = ensure_organization_for_profile(retailer)
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=customer)
        api_client.force_authenticate(user=retailer_user)
        resp = api_client.get(path.format(org=org.id, customer=customer.id))
        assert resp.status_code == expected, resp.data

    @pytest.mark.parametrize("url,body", [
        ("/api/cart/clear/", {"retailer_id": "abc"}),
        ("/api/cart/validate/", {"retailer_id": "abc"}),
        ("/api/cart/remove-coupon/", {"retailer_id": "abc"}),
        ("/api/customer/loyalty/redeem-otp/", {"retailer_id": "abc"}),
        ("/api/retailer/999999/reviews/create/", {"rating": 5}),
    ])
    def test_customer_posts_naming_no_real_shop_are_404(self, api_client, customer, url, body):
        api_client.force_authenticate(user=customer)
        assert api_client.post(url, body, format="json").status_code == 404

    @pytest.mark.parametrize("method,url,body", [
        ("post", "/api/customer/retailer/loyalty/redeem/", {"order_id": "abc"}),
        ("post", "/api/customer/retailer/loyalty/redeem-otp/", {"order_id": "abc"}),
        ("post", "/api/customer/retailer/loyalty/redeem-otp/", {"location_id": "abc", "customer_id": 1}),
        ("patch", "/api/products/bulk-update/", {"items": [1, 2]}),
    ])
    def test_shop_owner_writes_with_malformed_ids_are_400(
        self, api_client, retailer, retailer_user, method, url, body
    ):
        ensure_organization_for_profile(retailer)
        api_client.force_authenticate(user=retailer_user)
        resp = getattr(api_client, method)(url, body, format="json")
        assert resp.status_code == 400, resp.data


def test_search_limit_defaults_and_cap():
    from types import SimpleNamespace

    from products.views import SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX, _search_limit

    assert _search_limit(SimpleNamespace(query_params={})) == SEARCH_LIMIT_DEFAULT
    assert _search_limit(SimpleNamespace(query_params={"limit": "7"})) == 7
    assert _search_limit(SimpleNamespace(query_params={"limit": "100000"})) == SEARCH_LIMIT_MAX
