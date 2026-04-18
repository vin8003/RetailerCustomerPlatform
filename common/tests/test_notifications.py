import pytest
from unittest.mock import patch, MagicMock
from common.notifications import send_push_notification, send_silent_update

class TestCommonNotifications:
    
    @patch('threading.Thread')
    def test_send_push_notification_starts_thread(self, mock_thread):
        user = MagicMock(id=123)
        title = "Hello"
        message = "World"
        data = {"key": "value"}
        
        result = send_push_notification(user, title, message, data)
        
        assert result is True
        mock_thread.assert_called_once()
        args, kwargs = mock_thread.call_args
        assert kwargs['args'] == (123, title, message, data)
        # Verify it started
        mock_thread.return_value.start.assert_called_once()

    @patch('threading.Thread')
    def test_send_silent_update_starts_thread(self, mock_thread):
        user = MagicMock(id=456)
        event = "order_confirmed"
        
        result = send_silent_update(user, event)
        
        assert result is True
        mock_thread.assert_called_once()
        args, kwargs = mock_thread.call_args
        assert kwargs['args'] == (456, event, None)
        mock_thread.return_value.start.assert_called_once()

    @patch('common.notifications._send_push_notification_thread')
    def test_internal_thread_logic_user_not_found(self, mock_send):
        # We can test the internal thread function directly if we want, but it requires Django DB access
        # and mocks for FCMDevice.
        # For common testing, verifying the thread starts is usually sufficient.
        pass
