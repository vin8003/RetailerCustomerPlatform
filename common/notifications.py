from fcm_django.models import FCMDevice
from firebase_admin.messaging import Message, Notification, AndroidConfig, AndroidNotification
import logging

logger = logging.getLogger(__name__)

def send_push_notification(user, title, message, data=None):
    """
    Send a push notification to all devices registered to a user.
    """
    try:
        devices = FCMDevice.objects.filter(user=user, active=True)
        if not devices.exists():
            logger.info(f"No active devices found for user {user.username}")
            return False

        # Prepare the message
        # Default notification for visual display
        notification = Notification(title=title, body=message)
        
        # Android specific config (e.g. for high priority, sound, etc)
        android_config = AndroidConfig(
            priority='high',
            notification=AndroidNotification(
                sound='default',
                click_action='FLUTTER_NOTIFICATION_CLICK'
            )
        )

        # Send to all devices
        results = devices.send_message(
            Message(
                notification=notification,
                data=data or {},
                android=android_config
            )
        )
        
        logger.info(f"Notification sent to {user.username}. Success count: {results}")
        return True
    except Exception as e:
        logger.error(f"Error sending push notification to {user.username}: {str(e)}")
        return False

def send_silent_update(user, event_type, data=None):
    """
    Send a silent data-only message to trigger background updates in the app.
    """
    try:
        devices = FCMDevice.objects.filter(user=user, active=True)
        if not devices.exists():
            return False

        payload = {
            'event': event_type,
            'is_silent': 'true'
        }
        if data:
            payload.update(data)

        results = devices.send_message(
            Message(
                data=payload,
                android=AndroidConfig(priority='high')
            )
        )
        return True
    except Exception as e:
        logger.error(f"Error sending silent update to {user.username}: {str(e)}")
        return False
