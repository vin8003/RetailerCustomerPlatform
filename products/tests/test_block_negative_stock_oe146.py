"""
OE-146 / F-0033 — Block negative stock (thin EXTEND).

Sale deduct on POS and place_order blocks when on-hand would go
negative. The existing Product.reduce_quantity(allow_negative=True)
flag is the only override. No org/location policy model.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from cart.models import Cart, CartItem
from orders.models import Order
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
