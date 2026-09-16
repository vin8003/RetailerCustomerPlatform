"""
OE-146 / F-0033 — Block negative stock (thin EXTEND).

Sale deduct on POS and place_order blocks when on-hand would go
negative. The existing Product.reduce_quantity(allow_negative=True)
flag is the only override. No org/location policy model.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from cart.models import Cart, CartItem
from orders.models import Order, OrderItem
from products.models import Product, ProductBatch


def _pos_payload(product, quantity, *, batch=None, allow_negative=None):
    unit_price = batch.price if batch is not None else product.price
    item = {
        "product_id": product.id,
        "quantity": float(quantity),
        "unit_price": float(unit_price),
    }
    if batch is not None:
        item["batch_id"] = batch.id
    data = {
        "subtotal": float(unit_price * quantity),
        "total_amount": float(unit_price * quantity),
        "items": [item],
    }
    if allow_negative is not None:
        data["allow_negative"] = allow_negative
    return data


@pytest.mark.django_db
class TestPOSBlockNegativeStock:
    def test_pos_blocks_when_sale_would_go_negative(
        self, api_client, retailer_user, product
    ):
        product.quantity = Decimal("1")
        product.save(update_fields=["quantity"])
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("2")),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Not enough saleable stock" in response.data.get("error", "")
        product.refresh_from_db()
        assert product.quantity == Decimal("1")
        assert not Order.objects.filter(retailer=product.retailer, source="pos").exists()

    def test_pos_allows_sale_down_to_zero(
        self, api_client, retailer_user, product
    ):
        product.quantity = Decimal("2")
        product.save(update_fields=["quantity"])
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("2")),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        product.refresh_from_db()
        assert product.quantity == Decimal("0")

    def test_pos_allow_negative_true_overrides_block(
        self, api_client, retailer_user, product
    ):
        product.quantity = Decimal("0")
        product.save(update_fields=["quantity"])
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("2"), allow_negative=True),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        product.refresh_from_db()
        assert product.quantity == Decimal("-2")

    def test_pos_string_true_does_not_override(
        self, api_client, retailer_user, product
    ):
        product.quantity = Decimal("0")
        product.save(update_fields=["quantity"])
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("1"), allow_negative="true"),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        product.refresh_from_db()
        assert product.quantity == Decimal("0")

    def test_pos_batch_allow_negative_true_overrides_block(
        self, api_client, retailer_user, retailer, category, brand
    ):
        product = Product.objects.create(
            retailer=retailer,
            name="OE146 Batch Milk",
            category=category,
            brand=brand,
            price=Decimal("40.00"),
            has_batches=True,
            track_inventory=True,
            quantity=0,
            is_active=True,
            is_available=True,
        )
        batch = ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="OE146-EMPTY",
            price=Decimal("40.00"),
            quantity=0,
            is_active=True,
        )
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product, Decimal("1"), batch=batch, allow_negative=True),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        batch.refresh_from_db()
        assert batch.quantity == Decimal("-1")


@pytest.mark.django_db
class TestPlaceOrderBlockNegativeStock:
    def _checkout(self, api_client, customer, retailer, address):
        customer.is_phone_verified = True
        customer.save(update_fields=["is_phone_verified"])
        api_client.force_authenticate(user=customer)
        return api_client.post(
            reverse("place_order"),
            {
                "retailer_id": retailer.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "address_id": address.id,
            },
            format="json",
        )

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_blocks_when_sale_would_go_negative(
        self, mock_silent, mock_push, api_client, customer, retailer, address, product
    ):
        product.quantity = Decimal("1")
        product.save(update_fields=["quantity"])
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=Decimal("2"),
            unit_price=product.price,
        )

        response = self._checkout(api_client, customer, retailer, address)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        product.refresh_from_db()
        assert product.quantity == Decimal("1")
        assert not Order.objects.filter(retailer=retailer, customer=customer).exists()

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_body_allow_negative_is_ignored(
        self, mock_silent, mock_push, api_client, customer, retailer, address, product
    ):
        product.quantity = Decimal("0")
        product.save(update_fields=["quantity"])
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=Decimal("1"),
            unit_price=product.price,
        )
        customer.is_phone_verified = True
        customer.save(update_fields=["is_phone_verified"])
        api_client.force_authenticate(user=customer)

        response = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": retailer.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "address_id": address.id,
                "allow_negative": True,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        product.refresh_from_db()
        assert product.quantity == Decimal("0")
        assert not Order.objects.filter(retailer=retailer, customer=customer).exists()

    def test_place_order_deduct_allow_negative_true_overrides(
        self, product
    ):
        """Same reduce_quantity call place_order uses; only explicit True overrides."""
        product.quantity = Decimal("1")
        product.save(update_fields=["quantity"])

        blocked = product.reduce_quantity(Decimal("3"), allow_negative=False)
        product.refresh_from_db()
        assert blocked is False
        assert product.quantity == Decimal("1")

        allowed = product.reduce_quantity(Decimal("3"), allow_negative=True)
        product.refresh_from_db()
        assert allowed is True
        assert product.quantity == Decimal("-2")


def _zero_product_on_lock(monkeypatch, *products):
    """Simulate a concurrent last-unit sale that lands before our row lock."""
    pks = {product.pk for product in products}
    real_sfu = Product.objects.select_for_update

    def select_for_update_after_sale(*args, **kwargs):
        Product.objects.filter(pk__in=pks).update(quantity=Decimal("0"))
        return real_sfu(*args, **kwargs)

    monkeypatch.setattr(
        Product.objects, "select_for_update", select_for_update_after_sale
    )


def _record_locked_product_pks(monkeypatch):
    locked_pks = []
    real_sfu = Product.objects.select_for_update

    def tracking_sfu(*args, **kwargs):
        qs = real_sfu(*args, **kwargs)
        original_get = qs.get

        def tracking_get(*a, **kw):
            obj = original_get(*a, **kw)
            locked_pks.append(obj.pk)
            return obj

        qs.get = tracking_get
        return qs

    monkeypatch.setattr(Product.objects, "select_for_update", tracking_sfu)
    return locked_pks


def _record_lock_for_sale_calls(monkeypatch):
    """Capture lock_for_sale sold SKUs and the pk-ordered locked set."""
    calls = []
    real_lock = Product.lock_for_sale

    def tracking_lock(retailer, products):
        sold_pks = [product.pk for product in products]
        locked = real_lock(retailer, products)
        calls.append(
            {
                "sold_pks": sold_pks,
                "locked_pks": list(locked.keys()),
            }
        )
        return locked

    monkeypatch.setattr(Product, "lock_for_sale", staticmethod(tracking_lock))
    return calls


def _product_in_list_sql(captured_queries, *pks):
    """Product SELECTs that mention every pk (lock_for_sale id__in)."""
    needles = [str(pk) for pk in pks]
    return [
        query["sql"]
        for query in captured_queries
        if 'FROM "product"' in query["sql"]
        and " IN " in query["sql"].upper()
        and all(needle in query["sql"] for needle in needles)
    ]


def _make_pack_pair(retailer, category, brand, *, parent_qty=Decimal("1")):
    parent = Product.objects.create(
        retailer=retailer,
        name="OE146 Pack Rice 50kg",
        category=category,
        brand=brand,
        price=Decimal("2000.00"),
        quantity=parent_qty,
        track_inventory=True,
        is_active=True,
        is_available=True,
        is_parent_bulk=True,
        unit="kg",
    )
    child = Product.objects.create(
        retailer=retailer,
        name="OE146 Pack Rice 5kg",
        category=category,
        brand=brand,
        price=Decimal("250.00"),
        quantity=Decimal("0"),
        track_inventory=True,
        is_active=True,
        is_available=True,
        parent_bulk_product=parent,
        conversion_factor=Decimal("0.1000"),
        unit="kg",
    )
    parent.refresh_from_db()
    child.refresh_from_db()
    return parent, child


@pytest.mark.django_db
class TestSaleDeductLocksBeforeReduce:
    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_lock_sees_concurrent_last_unit_sale(
        self,
        mock_silent,
        mock_push,
        api_client,
        customer,
        retailer,
        address,
        product,
        monkeypatch,
    ):
        product.quantity = Decimal("1")
        product.save(update_fields=["quantity"])
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=Decimal("1"),
            unit_price=product.price,
        )
        _zero_product_on_lock(monkeypatch, product)

        customer.is_phone_verified = True
        customer.save(update_fields=["is_phone_verified"])
        api_client.force_authenticate(user=customer)
        response = api_client.post(
            reverse("place_order"),
            {
                "retailer_id": retailer.id,
                "delivery_mode": "delivery",
                "payment_mode": "cash",
                "address_id": address.id,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        product.refresh_from_db()
        # Concurrent UPDATE is in the same atomic and rolls back with the sale.
        assert product.quantity == Decimal("1")
        assert not Order.objects.filter(retailer=retailer, customer=customer).exists()

    def test_order_modify_lock_sees_concurrent_last_unit_sale(
        self, customer, retailer, address, product, monkeypatch
    ):
        from rest_framework.exceptions import ValidationError as DRFValidationError

        from orders.serializers import OrderModificationSerializer

        product.quantity = Decimal("1")
        product.save(update_fields=["quantity"])
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_address=address,
            delivery_mode="delivery",
            payment_mode="cash",
            subtotal=product.price,
            total_amount=product.price,
            status="pending",
        )
        item = OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=Decimal("1"),
            unit_price=product.price,
            total_price=product.price,
        )
        _zero_product_on_lock(monkeypatch, product)

        serializer = OrderModificationSerializer(
            order,
            data={"items": [{"id": item.id, "quantity": 2}]},
            context={},
        )
        assert serializer.is_valid(), serializer.errors
        with pytest.raises(DRFValidationError):
            serializer.save()

        product.refresh_from_db()
        item.refresh_from_db()
        assert product.quantity == Decimal("1")
        assert item.quantity == Decimal("1")

    def test_order_modify_multi_sku_uses_one_lock_for_sale_before_reduce(
        self, customer, retailer, address, category, brand, monkeypatch
    ):
        from orders.serializers import OrderModificationSerializer

        parent, child = _make_pack_pair(
            retailer, category, brand, parent_qty=Decimal("1")
        )
        parent.minimum_order_quantity = Decimal("0.001")
        parent.save(update_fields=["minimum_order_quantity"])
        standalone = Product.objects.create(
            retailer=retailer,
            name="OE146 Modify Tea",
            category=category,
            brand=brand,
            price=Decimal("10.00"),
            quantity=Decimal("5"),
            track_inventory=True,
            is_active=True,
            is_available=True,
        )
        assert parent.pk < child.pk
        high, low = (
            (standalone, child)
            if standalone.pk > child.pk
            else (child, standalone)
        )
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_address=address,
            delivery_mode="delivery",
            payment_mode="cash",
            subtotal=high.price + low.price,
            total_amount=high.price + low.price,
            status="pending",
        )
        item_high = OrderItem.objects.create(
            order=order,
            product=high,
            product_name=high.name,
            product_price=high.price,
            product_unit=high.unit,
            quantity=Decimal("1"),
            unit_price=high.price,
            total_price=high.price,
        )
        item_low = OrderItem.objects.create(
            order=order,
            product=low,
            product_name=low.name,
            product_price=low.price,
            product_unit=low.unit,
            quantity=Decimal("1"),
            unit_price=low.price,
            total_price=low.price,
        )
        events = []
        lock_calls = []
        real_lock = Product.lock_for_sale
        real_reduce = Product.reduce_quantity

        def tracking_lock(retailer_arg, products):
            sold_pks = [product.pk for product in products]
            events.append(("lock_for_sale", sold_pks))
            locked = real_lock(retailer_arg, products)
            lock_calls.append(
                {"sold_pks": sold_pks, "locked_pks": list(locked.keys())}
            )
            return locked

        def tracking_reduce(self, *args, **kwargs):
            events.append(("reduce", self.pk))
            return real_reduce(self, *args, **kwargs)

        monkeypatch.setattr(Product, "lock_for_sale", staticmethod(tracking_lock))
        monkeypatch.setattr(Product, "reduce_quantity", tracking_reduce)

        serializer = OrderModificationSerializer(
            order,
            data={
                "items": [
                    {"id": item_high.id, "quantity": 2},
                    {"id": item_low.id, "quantity": 2},
                ]
            },
            context={},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()

        assert events[0][0] == "lock_for_sale"
        assert any(kind == "reduce" for kind, _payload in events)
        assert next(
            i for i, (kind, _payload) in enumerate(events) if kind == "lock_for_sale"
        ) < next(i for i, (kind, _payload) in enumerate(events) if kind == "reduce")
        assert len(lock_calls) == 1
        assert lock_calls[0]["locked_pks"] == sorted(
            [parent.pk, child.pk, standalone.pk]
        )

    def test_reduce_quantity_relocks_stale_pack_parent(
        self, retailer, category, brand
    ):
        parent, child = _make_pack_pair(
            retailer, category, brand, parent_qty=Decimal("1")
        )
        Product.objects.filter(pk=parent.pk).update(quantity=Decimal("0"))
        assert parent.quantity == Decimal("1")

        blocked = child.reduce_quantity(Decimal("1"))

        assert blocked is False
        parent.refresh_from_db()
        assert parent.quantity == Decimal("0")

    def test_pos_pack_child_locks_parent_row(
        self, api_client, retailer_user, retailer, category, brand, monkeypatch
    ):
        parent, child = _make_pack_pair(
            retailer, category, brand, parent_qty=Decimal("1")
        )
        locked_pks = _record_locked_product_pks(monkeypatch)
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(child, Decimal("1")),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert parent.pk in locked_pks
        parent.refresh_from_db()
        assert parent.quantity == Decimal("0.900")

    def test_pos_pack_child_uses_one_lock_for_sale_before_reduce(
        self, api_client, retailer_user, retailer, category, brand, monkeypatch
    ):
        parent, child = _make_pack_pair(
            retailer, category, brand, parent_qty=Decimal("1")
        )
        assert parent.pk < child.pk
        events = []
        lock_calls = []
        real_lock = Product.lock_for_sale
        real_reduce = Product.reduce_quantity

        def tracking_lock(retailer_arg, products):
            sold_pks = [product.pk for product in products]
            events.append(("lock_for_sale", sold_pks))
            locked = real_lock(retailer_arg, products)
            lock_calls.append(
                {"sold_pks": sold_pks, "locked_pks": list(locked.keys())}
            )
            return locked

        def tracking_reduce(self, *args, **kwargs):
            events.append(("reduce", self.pk))
            return real_reduce(self, *args, **kwargs)

        monkeypatch.setattr(Product, "lock_for_sale", staticmethod(tracking_lock))
        monkeypatch.setattr(Product, "reduce_quantity", tracking_reduce)
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(child, Decimal("1")),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert events[0][0] == "lock_for_sale"
        assert events[0][1] == [child.pk]
        assert any(kind == "reduce" for kind, _payload in events)
        assert next(
            i for i, (kind, _payload) in enumerate(events) if kind == "lock_for_sale"
        ) < next(i for i, (kind, _payload) in enumerate(events) if kind == "reduce")
        assert len(lock_calls) == 1
        assert lock_calls[0]["locked_pks"] == sorted([parent.pk, child.pk])

    def test_pos_pack_lock_for_sale_covers_parent_and_child_in_one_ordered_sfu(
        self, api_client, retailer_user, retailer, category, brand
    ):
        parent, child = _make_pack_pair(
            retailer, category, brand, parent_qty=Decimal("1")
        )
        assert parent.pk < child.pk
        api_client.force_authenticate(user=retailer_user)

        with CaptureQueriesContext(connection) as ctx:
            response = api_client.post(
                reverse("create_pos_order"),
                _pos_payload(child, Decimal("1")),
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED
        joint = _product_in_list_sql(ctx.captured_queries, parent.pk, child.pk)
        assert joint, "POS must lock pack parent+child in one lock_for_sale"
        assert "ORDER BY" in joint[0].upper()

    def test_pos_multi_sku_uses_one_lock_for_sale_for_every_sold_sku(
        self, api_client, retailer_user, retailer, category, brand, monkeypatch
    ):
        parent, child = _make_pack_pair(
            retailer, category, brand, parent_qty=Decimal("1")
        )
        standalone = Product.objects.create(
            retailer=retailer,
            name="OE146 Standalone Tea",
            category=category,
            brand=brand,
            price=Decimal("10.00"),
            quantity=Decimal("5"),
            track_inventory=True,
            is_active=True,
            is_available=True,
        )
        lock_calls = _record_lock_for_sale_calls(monkeypatch)
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            {
                "subtotal": float(child.price + standalone.price),
                "total_amount": float(child.price + standalone.price),
                "items": [
                    {
                        "product_id": child.id,
                        "quantity": 1,
                        "unit_price": float(child.price),
                    },
                    {
                        "product_id": standalone.id,
                        "quantity": 1,
                        "unit_price": float(standalone.price),
                    },
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(lock_calls) == 1
        assert lock_calls[0]["sold_pks"] == [child.pk, standalone.pk]
        assert lock_calls[0]["locked_pks"] == sorted(
            [parent.pk, child.pk, standalone.pk]
        )
