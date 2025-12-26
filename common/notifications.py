from fcm_django.models import FCMDevice
from firebase_admin.messaging import Message, Notification, AndroidConfig, AndroidNotification
import logging
import threading

logger = logging.getLogger(__name__)

def _send_push_notification_thread(user_id, title, message, data=None):
    """
    Internal function to send push notification in a background thread.
    """
    try:
        from authentication.models import User
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.warning(f"User {user_id} not found for notification")
            return

        devices = FCMDevice.objects.filter(user=user, active=True)
        if not devices.exists():
            logger.info(f"No active devices found for user {user.username}")
            return

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
    except Exception as e:
        logger.error(f"Error sending push notification to user {user_id}: {str(e)}")

def send_push_notification(user, title, message, data=None):
    """
    Send a push notification to all devices registered to a user.
    Runs in a separate thread to avoid blocking the API response.
    """
    try:
        thread = threading.Thread(
            target=_send_push_notification_thread,
            args=(user.id, title, message, data)
        )
        thread.start()
        return True
    except Exception as e:
        logger.error(f"Error starting notification thread: {str(e)}")
        return False

def _send_silent_update_thread(user_id, event_type, data=None):
    """
    Internal function to send silent update in a background thread.
    """
    try:
        from authentication.models import User
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return

        devices = FCMDevice.objects.filter(user=user, active=True)
        if not devices.exists():
            return

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
        logger.info(f"Silent update sent to {user.username}")
    except Exception as e:
        logger.error(f"Error sending silent update to user {user_id}: {str(e)}")

def send_silent_update(user, event_type, data=None):
    """
    Send a silent data-only message to trigger background updates in the app.
    Runs in a separate thread.
    """
    try:
        thread = threading.Thread(
            target=_send_silent_update_thread,
            args=(user.id, event_type, data)
        )
        thread.start()
        return True
    except Exception as e:
        logger.error(f"Error starting silent update thread: {str(e)}")
        return False
