import os
import hashlib
from decimal import Decimal
from unittest.mock import patch, MagicMock
from common.meta_tracking import (
    _hash_value,
    _normalize_phone,
    _dispatch_meta_event,
    track_meta_purchase,
    META_GRAPH_API_VERSION,
)


class TestMetaTrackingUtils:
    def test_hash_value(self):
        val = " Test@Example.COM "
        expected = hashlib.sha256(b"test@example.com").hexdigest()
        assert _hash_value(val) == expected
        assert _hash_value("") == ""
        assert _hash_value(None) == ""

    def test_normalize_phone_10_digits(self):
        assert _normalize_phone("9876543210") == "919876543210"

    def test_normalize_phone_with_country_code(self):
        assert _normalize_phone("+91-98765-43210") == "919876543210"

    def test_normalize_phone_empty(self):
        assert _normalize_phone("") == ""
        assert _normalize_phone(None) == ""


class TestTrackMetaPurchase:
    @patch.dict(os.environ, {
        "META_DATASET_ID": "2283127902475188",
        "META_ACCESS_TOKEN": "mock_token_secret"
    })
    @patch("threading.Thread")
    def test_track_meta_purchase_dispatches_correct_payload(self, mock_thread):
        customer = MagicMock(
            phone_number="9876543210",
            email="shopper@test.com",
            first_name="Rahul",
            last_name="Verma",
            username="rahul9876",
        )

        item1 = MagicMock(
            product_id=101,
            quantity=Decimal("0.500"),  # Loose / fractional item
            unit_price=Decimal("80.00"),
        )
        item2 = MagicMock(
            product_id=202,
            quantity=Decimal("2.000"),
            unit_price=Decimal("50.00"),
        )

        mock_items_manager = MagicMock()
        mock_items_manager.all.return_value = [item1, item2]

        order = MagicMock(
            order_number="OE-2026-8888",
            total_amount=Decimal("140.00"),
            customer=customer,
            items=mock_items_manager,
        )

        request = MagicMock()
        request.META = {
            "HTTP_X_FORWARDED_FOR": "203.0.113.195, 192.168.1.1",
            "HTTP_USER_AGENT": "Mozilla/5.0 OrderEasyCustomerApp",
        }

        track_meta_purchase(order, request=request, test_event_code="TEST_CODE_123")

        mock_thread.assert_called_once()
        _, kwargs = mock_thread.call_args
        assert kwargs["daemon"] is True

        payload, dataset_id = kwargs["args"]
        assert dataset_id == "2283127902475188"
        assert payload["access_token"] == "mock_token_secret"
        assert payload["test_event_code"] == "TEST_CODE_123"

        event = payload["data"][0]
        assert event["event_name"] == "Purchase"
        assert event["event_id"] == "OE-2026-8888"
        assert event["action_source"] == "website"

        # User data assertions
        user_data = event["user_data"]
        assert user_data["ph"] == [_hash_value("919876543210")]
        assert user_data["em"] == [_hash_value("shopper@test.com")]
        assert user_data["fn"] == [_hash_value("Rahul")]
        assert user_data["ln"] == [_hash_value("Verma")]
        assert user_data["client_ip_address"] == "203.0.113.195"
        assert user_data["client_user_agent"] == "Mozilla/5.0 OrderEasyCustomerApp"

        # Custom data assertions
        custom_data = event["custom_data"]
        assert custom_data["currency"] == "INR"
        assert custom_data["value"] == 140.00
        assert custom_data["order_id"] == "OE-2026-8888"

        # Contents with fractional quantity preserved as float
        contents = custom_data["contents"]
        assert len(contents) == 2
        assert contents[0] == {"id": "101", "quantity": 0.5, "item_price": 80.00}
        assert contents[1] == {"id": "202", "quantity": 2.0, "item_price": 50.00}

        # Thread start
        mock_thread.return_value.start.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch("threading.Thread")
    def test_track_meta_purchase_skipped_without_env(self, mock_thread):
        order = MagicMock()
        track_meta_purchase(order)
        mock_thread.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_dispatch_meta_event_sends_token_in_body_not_url(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"events_received": 1}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {
            "data": [{"event_name": "Purchase"}],
            "access_token": "secret_access_token_123"
        }
        dataset_id = "2283127902475188"

        _dispatch_meta_event(payload, dataset_id)

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]

        # Verify token is in body and NOT in URL query string
        expected_url = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/{dataset_id}/events"
        assert req.get_full_url() == expected_url
        assert "access_token" not in req.get_full_url()

        body_json = req.data.decode("utf-8")
        assert "secret_access_token_123" in body_json
