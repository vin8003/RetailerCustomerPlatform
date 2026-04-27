import pytest
from decimal import Decimal
from unittest.mock import patch
from orders.models import (
    Order, OrderItem, OrderStatusLog, OrderDelivery,
    OrderFeedback, OrderReturn, OrderChatMessage, RetailerRating,
)
from customers.models import CustomerLoyalty, LoyaltyTransaction, CustomerProfile


@pytest.mark.django_db
class TestOrderModel:

    def test_order_str(self, order):
        assert f"Order #" in str(order)
        assert "order_customer" in str(order)

    def test_order_number_auto_generated(self, order):
        assert order.order_number.startswith("ORD-")

    def test_can_be_cancelled(self, order):
        order.status = "pending"
        assert order.can_be_cancelled is True
        order.status = "confirmed"
        assert order.can_be_cancelled is True
        order.status = "processing"
        assert order.can_be_cancelled is True
        order.status = "delivered"
        assert order.can_be_cancelled is False
        order.status = "cancelled"
        assert order.can_be_cancelled is False

    def test_is_completed(self, order):
        order.status = "pending"
        assert order.is_completed is False
        order.status = "delivered"
        assert order.is_completed is True
        order.status = "cancelled"
        assert order.is_completed is True
        order.status = "returned"
        assert order.is_completed is True

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_update_status_confirmed(self, mock_silent, mock_push, order):
        order.update_status("confirmed", user=None)
        assert order.status == "confirmed"
        assert order.confirmed_at is not None
        assert OrderStatusLog.objects.filter(order=order, new_status="confirmed").exists()

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_update_status_delivered_awards_points(self, mock_silent, mock_push, order, retailer):
        from retailers.models import RetailerRewardConfig
        RetailerRewardConfig.objects.create(
            retailer=retailer,
            earning_type="percentage",
            loyalty_earning_value=Decimal("5.00"),
            loyalty_min_order_value=Decimal("0.00"),
            is_active=True,
        )
        order.update_status("delivered", user=None)
        assert order.status == "delivered"
        assert order.delivered_at is not None
        # Check loyalty was awarded
        loyalty = CustomerLoyalty.objects.get(customer=order.customer, retailer=retailer)
        assert loyalty.points > 0
        assert LoyaltyTransaction.objects.filter(
            customer=order.customer, transaction_type="earn"
        ).exists()

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_update_status_cancelled_refunds_points(self, mock_silent, mock_push, order, retailer):
        order.points_redeemed = Decimal("50.00")
        order.save()
        order.update_status("cancelled", user=None)
        assert order.status == "cancelled"
        assert order.cancelled_at is not None
        loyalty = CustomerLoyalty.objects.get(customer=order.customer, retailer=retailer)
        assert loyalty.points == Decimal("50.00")
        assert LoyaltyTransaction.objects.filter(transaction_type="refund").exists()

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_update_status_cancelled_reverts_earned(self, mock_silent, mock_push, order, retailer):
        order.status = 'delivered'
        order.points_earned = Decimal("10.00")
        order.save()
        order.update_status("cancelled", user=None)
        assert order.points_earned == 0

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_update_status_customer_notifies_retailer(self, mock_silent, mock_push, order, customer):
        order.update_status("confirmed", user=customer)
        # Should send push to retailer too
        assert mock_push.call_count >= 2  # customer + retailer


@pytest.mark.django_db
class TestOrderItemModel:

    def test_order_item_str(self, order):
        item = order.items.first()
        assert "Order Product x 2" == str(item)

    def test_save_calculates_total(self, order, product):
        item = OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=3,
            unit_price=Decimal("100.00"),
            total_price=Decimal("0.00"),  # will be overwritten in save
        )
        assert item.total_price == Decimal("300.00")


@pytest.mark.django_db
class TestOrderStatusLogModel:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_status_log_str(self, mock_silent, mock_push, order):
        order.update_status("confirmed")
        log = OrderStatusLog.objects.filter(order=order).first()
        assert "pending" in str(log)
        assert "confirmed" in str(log)


@pytest.mark.django_db
class TestOrderDeliveryModel:

    def test_delivery_str(self, order):
        delivery = OrderDelivery.objects.create(order=order)
        assert f"Delivery for Order #{order.order_number}" == str(delivery)


@pytest.mark.django_db
class TestOrderFeedbackModel:

    def test_feedback_str(self, order):
        fb = OrderFeedback.objects.create(
            order=order,
            customer=order.customer,
            overall_rating=4,
            product_quality_rating=5,
            delivery_rating=4,
            service_rating=3,
        )
        assert f"Feedback for Order #{order.order_number}" == str(fb)


@pytest.mark.django_db
class TestOrderReturnModel:

    def test_return_str(self, order):
        ret = OrderReturn.objects.create(
            order=order,
            customer=order.customer,
            reason="defective",
            description="Broken item",
        )
        assert f"Return request for Order #{order.order_number}" == str(ret)


@pytest.mark.django_db
class TestOrderChatMessageModel:

    def test_chat_str(self, order, customer):
        msg = OrderChatMessage.objects.create(
            order=order,
            sender=customer,
            message="Hello, is my order ready?",
        )
        assert "Hello, is my order" in str(msg)


@pytest.mark.django_db
class TestRetailerRatingSignal:

    @patch("common.notifications.send_push_notification")
    @patch("common.notifications.send_silent_update")
    def test_feedback_updates_retailer_avg(self, mock_silent, mock_push, order, retailer):
        OrderFeedback.objects.create(
            order=order,
            customer=order.customer,
            overall_rating=4,
            product_quality_rating=5,
            delivery_rating=4,
            service_rating=3,
        )
        retailer.refresh_from_db()
        assert retailer.average_rating == Decimal("4.00")
        assert retailer.total_ratings == 1

    def test_retailer_rating_zero_blacklists(self, order, retailer, customer):
        from retailers.models import RetailerBlacklist
        RetailerRating.objects.create(
            order=order,
            retailer=retailer,
            customer=customer,
            rating=0,
        )
        assert RetailerBlacklist.objects.filter(
            retailer=retailer, customer=customer
        ).exists()

    def test_retailer_rating_updates_customer_avg(self, order, retailer, customer):
        RetailerRating.objects.create(
            order=order,
            retailer=retailer,
            customer=customer,
            rating=4,
        )
        profile = CustomerProfile.objects.get(user=customer)
        assert profile.average_rating == Decimal("4.00")
        assert profile.total_ratings == 1
