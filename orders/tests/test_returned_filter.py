import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status

from orders.models import Order, OrderItem
from orders.status_filters import apply_order_status_filter
from returns.models import SalesReturn
from returns.services import process_sales_return


@pytest.mark.django_db
class TestReturnedStatusFilter:
    def test_helper_includes_status_returned_and_sales_returns(
        self, retailer, customer, address, product
    ):
        status_returned = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_address=address,
            delivery_mode="delivery",
            payment_mode="cash",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="returned",
        )
        delivered_with_return = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_address=address,
            delivery_mode="delivery",
            payment_mode="cash",
            subtotal=Decimal("80.00"),
            total_amount=Decimal("80.00"),
            status="delivered",
        )
        SalesReturn.objects.create(
            retailer=retailer,
            order=delivered_with_return,
            customer=customer,
            refund_amount=Decimal("80.00"),
            refund_payment_mode="cash",
        )
        still_delivered = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_address=address,
            delivery_mode="delivery",
            payment_mode="cash",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
            status="delivered",
        )

        filtered = apply_order_status_filter(Order.objects.all(), "returned")
        ids = set(filtered.values_list("id", flat=True))
        assert status_returned.id in ids
        assert delivered_with_return.id in ids
        assert still_delivered.id not in ids

    def test_history_returned_tab_does_not_500(
        self, api_client, retailer_user, retailer, customer, address, product
    ):
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            delivery_address=address,
            delivery_mode="delivery",
            payment_mode="cash",
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
            status="delivered",
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=2,
            unit_price=product.price,
            total_price=Decimal("200.00"),
        )
        SalesReturn.objects.create(
            retailer=retailer,
            order=order,
            customer=customer,
            refund_amount=Decimal("200.00"),
            refund_payment_mode="cash",
        )

        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_order_history"), {"status": "returned"})
        assert res.status_code == status.HTTP_200_OK
        results = res.data.get("results", res.data)
        ids = [row["id"] for row in results]
        assert order.id in ids
        matching = next(row for row in results if row["id"] == order.id)
        assert matching["is_returned"] is True

    def test_full_sales_return_sets_order_status_returned(
        self, retailer_user, retailer, customer, product
    ):
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
            status="delivered",
            payment_mode="cash",
        )
        item = OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=2,
            unit_price=product.price,
            total_price=Decimal("200.00"),
        )
        process_sales_return(
            retailer=retailer,
            order=order,
            items_data=[{
                "product": product,
                "quantity": 2,
                "refund_unit_price": product.price,
                "order_item": item,
            }],
            refund_payment_mode="cash",
            reason="Full return",
            created_by=retailer_user,
        )
        order.refresh_from_db()
        assert order.status == "returned"

    def test_partial_sales_return_keeps_delivered(
        self, retailer_user, retailer, customer, product
    ):
        order = Order.objects.create(
            customer=customer,
            retailer=retailer,
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
            status="delivered",
            payment_mode="cash",
        )
        item = OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=2,
            unit_price=product.price,
            total_price=Decimal("200.00"),
        )
        process_sales_return(
            retailer=retailer,
            order=order,
            items_data=[{
                "product": product,
                "quantity": 1,
                "refund_unit_price": product.price,
                "order_item": item,
            }],
            refund_payment_mode="cash",
            reason="Partial return",
            created_by=retailer_user,
        )
        order.refresh_from_db()
        assert order.status == "delivered"
        assert apply_order_status_filter(Order.objects.all(), "returned").filter(id=order.id).exists()
