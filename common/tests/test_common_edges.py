import pytest
from unittest.mock import patch, MagicMock
from common.notifications import _send_push_notification_thread, _send_silent_update_thread
from common.utils import resize_image, validate_phone_number
from common.permissions import IsRetailerUser

@pytest.mark.django_db
class TestCommonEdges:
    
    @patch('fcm_django.models.FCMDevice.objects.filter')
    def test_send_push_notification_thread_success(self, mock_device_filter, retailer_user):
        # Trigger lines 17-47 in common/notifications.py
        mock_devices = MagicMock()
        mock_devices.exists.return_value = True
        mock_devices.send_message.return_value = 1
        mock_device_filter.return_value = mock_devices
        
        _send_push_notification_thread(retailer_user.id, "Title", "Body")
        mock_devices.send_message.assert_called_once()

    def test_send_push_notification_thread_user_not_found(self):
        # Trigger lines 17-18
        with patch('common.notifications.logger') as mock_logger:
            _send_push_notification_thread(9999, "Title", "Body")
            mock_logger.warning.assert_called()

    @patch('fcm_django.models.FCMDevice.objects.filter')
    def test_send_silent_update_thread_success(self, mock_device_filter, retailer_user):
        # Trigger lines 71-97
        mock_devices = MagicMock()
        mock_devices.exists.return_value = True
        mock_device_filter.return_value = mock_devices
        
        _send_silent_update_thread(retailer_user.id, "order_update")
        mock_devices.send_message.assert_called_once()

    def test_validate_phone_number_edges(self):
        # Trigger coverage for common/utils.py phone validation
        # Returns (is_valid, message)
        is_valid, _ = validate_phone_number("1234")
        assert is_valid is False
        
        is_valid, _ = validate_phone_number("abcd123456")
        assert is_valid is False
        
        is_valid, _ = validate_phone_number("1234567890")
        assert is_valid is True

    @patch('PIL.Image.open')
    def test_resize_image_exception(self, mock_open):
        # Trigger lines 40-50 in common/utils.py
        mock_open.side_effect = Exception("Corrupt image")
        result = resize_image(MagicMock())
        assert result is False

    def test_permission_attribute_safety(self):
        # Trigger lines in common/permissions.py where hasattr fails
        perm = IsRetailerUser()
        request = MagicMock()
        request.user.user_type = 'customer'
        # customer user might not have 'retailer_profile'
        if hasattr(request.user, 'retailer_profile'):
            del request.user.retailer_profile
        assert perm.has_permission(request, None) is False
