import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from unittest.mock import patch
from orders.models import Order, OrderItem, OrderFeedback, OrderReturn, OrderChatMessage
from orders.models import PaymentTransaction


@pytest.mark.django_db
class TestPlaceOrder:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_place_order_success(self, mock_silent, mock_push, api_client, customer, cart_with_items, address, retailer):
        customer.is_phone_verified = True
        customer.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("place_order"), {
            "retailer_id": retailer.id,
            "delivery_mode": "delivery",
            "payment_mode": "cash",
            "address_id": address.id,
        })
        assert res.status_code == status.HTTP_201_CREATED
        assert Order.objects.filter(customer=customer).exists()

    def test_place_order_retailer_forbidden(self, api_client, retailer_user):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(reverse("place_order"), {})
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_place_order_phone_not_verified(self, api_client, customer):
        customer.is_phone_verified = False
        customer.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("place_order"), {})
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_place_order_missing_data(self, api_client, customer):
        customer.is_phone_verified = True
        customer.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("place_order"), {})
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestGetCurrentOrders:

    def test_customer_current_orders(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_current_orders"))
        assert res.status_code == status.HTTP_200_OK

    def test_retailer_current_orders(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_current_orders"))
        assert res.status_code == status.HTTP_200_OK

    def test_current_orders_with_status_filter(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_current_orders"), {"status": "pending"})
        assert res.status_code == status.HTTP_200_OK

    def test_current_orders_with_search(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_current_orders"), {"search": order.order_number})
        assert res.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestGetOrderHistory:

    def test_customer_order_history(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_order_history"))
        assert res.status_code == status.HTTP_200_OK

    def test_retailer_order_history(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_order_history"))
        assert res.status_code == status.HTTP_200_OK

    def test_order_history_with_date_filter(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_order_history"), {
            "start_date": "2020-01-01",
            "end_date": "2030-12-31",
        })
        assert res.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestGetOrderDetail:

    def test_customer_order_detail(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["order_number"] == order.order_number

    def test_retailer_order_detail(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert res.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestCancelOrder:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_cancel_order_success(self, mock_silent, mock_push, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("cancel_order", args=[order.id]),
            {"reason": "Changed my mind"},
        )
        assert res.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.status == "cancelled"

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_cancel_order_not_cancellable(self, mock_silent, mock_push, api_client, customer, order):
        order.status = "delivered"
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("cancel_order", args=[order.id]))
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestUpdateOrderStatus:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_update_status_retailer(self, mock_silent, mock_push, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "confirmed"},
        )
        assert res.status_code == status.HTTP_200_OK

    def test_update_status_customer_forbidden(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.patch(
            reverse("update_order_status", args=[order.id]),
            {"status": "confirmed"},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestOrderFeedback:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_create_feedback_success(self, mock_silent, mock_push, api_client, customer, order):
        order.status = "delivered"
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("create_order_feedback", args=[order.id]),
            {
                "overall_rating": 5,
                "product_quality_rating": 5,
                "delivery_rating": 4,
                "service_rating": 4,
                "comment": "Great service!",
            },
        )
        assert res.status_code == status.HTTP_201_CREATED

    def test_create_feedback_retailer_forbidden(self, api_client, retailer_user, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("create_order_feedback", args=[order.id]),
            {"overall_rating": 5, "product_quality_rating": 5, "delivery_rating": 4, "service_rating": 4},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCreateReturnRequest:

    def test_create_return_success(self, api_client, customer, order):
        order.status = "delivered"
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("create_return_request", args=[order.id]),
            {"reason": "defective", "description": "Product was broken"},
        )
        assert res.status_code == status.HTTP_201_CREATED

    def test_create_return_retailer_forbidden(self, api_client, retailer_user, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("create_return_request", args=[order.id]),
            {"reason": "defective", "description": "Broken"},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestOrderStats:

    def test_get_stats_retailer(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_order_stats"))
        assert res.status_code == status.HTTP_200_OK
        assert "total_orders" in res.data

    def test_get_stats_customer_forbidden(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_order_stats"))
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_get_stats_with_time_range(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        for tr in ["today", "this_week", "this_month"]:
            res = api_client.get(reverse("get_order_stats"), {"time_range": tr})
            assert res.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestRetailerReviews:

    def test_get_reviews_retailer(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_retailer_reviews"))
        assert res.status_code == status.HTTP_200_OK

    def test_get_reviews_customer_forbidden(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_retailer_reviews"))
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestOrderChat:

    @patch("common.notifications.send_push_notification")
    def test_send_message_customer(self, mock_push, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("send_order_message", args=[order.id]),
            {"message": "Is my order ready?"},
        )
        assert res.status_code == status.HTTP_201_CREATED

    @patch("common.notifications.send_push_notification")
    def test_send_message_retailer(self, mock_push, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("send_order_message", args=[order.id]),
            {"message": "Your order will be ready soon."},
        )
        assert res.status_code == status.HTTP_201_CREATED

    def test_send_empty_message(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("send_order_message", args=[order.id]),
            {"message": ""},
        )
        assert res.status_code == 400

    def test_get_chat(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        OrderChatMessage.objects.create(order=order, sender=customer, message="Hi")
        res = api_client.get(reverse("get_order_chat", args=[order.id]))
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) == 1

    @patch("common.notifications.send_push_notification")
    def test_mark_chat_read(self, mock_push, api_client, customer, order, retailer_user):
        OrderChatMessage.objects.create(order=order, sender=retailer_user, message="Ready!")
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("mark_chat_read", args=[order.id]))
        assert res.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestPaymentFlow:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_submit_payment_success(self, mock_silent, mock_push, api_client, customer, order):
        order.payment_mode = "upi"
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("submit_payment", args=[order.id]),
            {"payment_reference_id": "123456789012"},
        )
        assert res.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.payment_status == "pending_verification"


@pytest.mark.django_db
class TestPaymentSerializationCompatibility:
    def test_order_detail_schema_unchanged_with_transactions(self, api_client, customer, order):
        PaymentTransaction.objects.create(
            order=order,
            method="cash",
            amount=Decimal("90.00"),
            status="verified",
        )
        PaymentTransaction.objects.create(
            order=order,
            method="upi",
            amount=Decimal("110.00"),
            reference_id="123456789012",
            status="pending_verification",
        )
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["payment_status"] == "pending_verification"
        assert Decimal(str(res.data["cash_amount"])) == Decimal("90.00")
        assert Decimal(str(res.data["upi_amount"])) == Decimal("110.00")

    def test_order_detail_legacy_fallback_without_transactions(self, api_client, customer, order):
        order.cash_amount = Decimal("75.00")
        order.payment_status = "verified"
        order.payment_reference_id = "LEGACYREF"
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["payment_status"] == "verified"
        assert res.data["payment_reference_id"] == "LEGACYREF"
        assert Decimal(str(res.data["cash_amount"])) == Decimal("75.00")

    def test_submit_payment_non_upi(self, api_client, customer, order):
        order.payment_mode = "cash"
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("submit_payment", args=[order.id]),
            {"payment_reference_id": "123456789012"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_submit_payment_locked(self, api_client, customer, order):
        order.payment_mode = "upi"
        order.is_payment_locked = True
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("submit_payment", args=[order.id]),
            {"payment_reference_id": "123456789012"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_submit_payment_max_edits(self, api_client, customer, order):
        order.payment_mode = "upi"
        order.payment_edit_count = 3
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("submit_payment", args=[order.id]),
            {"payment_reference_id": "123456789012"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_submit_payment_invalid_format(self, api_client, customer, order):
        order.payment_mode = "upi"
        order.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("submit_payment", args=[order.id]),
            {"payment_reference_id": "abc"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_verify_payment_success(self, mock_silent, mock_push, api_client, retailer_user, retailer, order):
        order.payment_mode = "upi"
        order.payment_reference_id = "123456789012"
        order.payment_status = "pending_verification"
        order.save()
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("verify_payment", args=[order.id]),
            {"action": "verify"},
        )
        assert res.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.payment_status == "verified"
        assert order.is_payment_locked is True

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_verify_payment_fail(self, mock_silent, mock_push, api_client, retailer_user, retailer, order):
        order.payment_mode = "upi"
        order.payment_reference_id = "123456789012"
        order.save()
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("verify_payment", args=[order.id]),
            {"action": "fail"},
        )
        assert res.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.payment_status == "failed"

    def test_verify_payment_invalid_action(self, api_client, retailer_user, retailer, order):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("verify_payment", args=[order.id]),
            {"action": "invalid"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_verify_payment_customer_forbidden(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("verify_payment", args=[order.id]),
            {"action": "verify"},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestEstimatedTime:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_update_estimated_time(self, mock_silent, mock_push, api_client, retailer_user, retailer, order):
        order.status = "confirmed"
        order.save()
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(
            reverse("update_estimated_time", args=[order.id]),
            {"preparation_time_minutes": 30},
        )
        assert res.status_code == status.HTTP_200_OK
        order.refresh_from_db()
        assert order.preparation_time_minutes == 30

    def test_update_estimated_time_wrong_status(self, api_client, retailer_user, retailer, order):
        order.status = "delivered"
        order.save()
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(
            reverse("update_estimated_time", args=[order.id]),
            {"preparation_time_minutes": 30},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_estimated_time_missing(self, api_client, retailer_user, retailer, order):
        order.status = "confirmed"
        order.save()
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(reverse("update_estimated_time", args=[order.id]))
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_estimated_time_negative(self, api_client, retailer_user, retailer, order):
        order.status = "confirmed"
        order.save()
        api_client.force_authenticate(user=retailer_user)
        res = api_client.patch(
            reverse("update_estimated_time", args=[order.id]),
            {"preparation_time_minutes": -5},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_estimated_time_customer_forbidden(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.patch(
            reverse("update_estimated_time", args=[order.id]),
            {"preparation_time_minutes": 30},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCreateRetailerRating:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_rate_customer_success(self, mock_silent, mock_push, api_client, retailer_user, retailer, order):
        # Order must be completed to rate
        order.update_status("confirmed", user=retailer_user)
        order.update_status("processing", user=retailer_user)
        order.update_status("packed", user=retailer_user)
        order.update_status("delivered", user=retailer_user)
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("create_retailer_rating", args=[order.id]),
            {"rating": 4, "comment": "Good customer"},
        )
        assert res.status_code == status.HTTP_201_CREATED

    def test_rate_customer_forbidden(self, api_client, customer, order):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("create_retailer_rating", args=[order.id]),
            {"rating": 4},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
