"""
Versioned order notification catalog (OE-183 / F-0005).

Event name → template → channel. Statutory types cannot be disabled by retailers.
"""

NOTIFICATION_CATALOG_VERSION = 1

CHANNEL_PUSH = 'push'
CHANNEL_SMS = 'sms'
CHANNEL_IN_APP = 'in_app'

ALL_CHANNELS = frozenset({CHANNEL_PUSH, CHANNEL_SMS, CHANNEL_IN_APP})

# notification_type -> definition
NOTIFICATION_DEFINITIONS = {
    'order.status.confirmed': {
        'event_name': 'order.status.confirmed',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Your order has been confirmed',
        'default_channel': CHANNEL_PUSH,
        'statutory': False,
    },
    'order.status.processing': {
        'event_name': 'order.status.processing',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Your order is being processed',
        'default_channel': CHANNEL_PUSH,
        'statutory': False,
    },
    'order.status.packed': {
        'event_name': 'order.status.packed',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Your order has been packed',
        'default_channel': CHANNEL_PUSH,
        'statutory': False,
    },
    'order.status.out_for_delivery': {
        'event_name': 'order.status.out_for_delivery',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Your order is out for delivery',
        'default_channel': CHANNEL_PUSH,
        'statutory': False,
    },
    'order.status.delivered': {
        'event_name': 'order.status.delivered',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Your order has been delivered',
        'default_channel': CHANNEL_PUSH,
        'statutory': True,
    },
    'order.status.cancelled': {
        'event_name': 'order.status.cancelled',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Your order has been cancelled',
        'default_channel': CHANNEL_PUSH,
        'statutory': True,
    },
    'order.status.returned': {
        'event_name': 'order.status.returned',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Your order has been returned',
        'default_channel': CHANNEL_PUSH,
        'statutory': True,
    },
    'order.status.waiting_for_customer_approval': {
        'event_name': 'order.status.waiting_for_customer_approval',
        'title_template': 'Order Update: #{order_number}',
        'message_template': 'Order modifications require your approval',
        'default_channel': CHANNEL_PUSH,
        'statutory': False,
    },
}

ALL_NOTIFICATION_TYPES = frozenset(NOTIFICATION_DEFINITIONS.keys())
STATUTORY_NOTIFICATION_TYPES = frozenset(
    code for code, spec in NOTIFICATION_DEFINITIONS.items() if spec['statutory']
)
NON_STATUTORY_NOTIFICATION_TYPES = ALL_NOTIFICATION_TYPES - STATUTORY_NOTIFICATION_TYPES

# Map order.status values to notification type codes.
ORDER_STATUS_TO_NOTIFICATION_TYPE = {
    'confirmed': 'order.status.confirmed',
    'processing': 'order.status.processing',
    'packed': 'order.status.packed',
    'out_for_delivery': 'order.status.out_for_delivery',
    'delivered': 'order.status.delivered',
    'cancelled': 'order.status.cancelled',
    'returned': 'order.status.returned',
    'waiting_for_customer_approval': 'order.status.waiting_for_customer_approval',
}

MAX_DELIVERY_RETRIES = 3


def is_known_notification_type(code: str) -> bool:
    return code in ALL_NOTIFICATION_TYPES


def is_statutory_notification_type(code: str) -> bool:
    return code in STATUTORY_NOTIFICATION_TYPES


def notification_type_for_order_status(status: str):
    """Return notification type code for an order status, or None."""
    return ORDER_STATUS_TO_NOTIFICATION_TYPE.get(status)


def render_template(template: str, context: dict) -> str:
    """Simple ``{key}`` substitution for notification templates."""
    result = template
    for key, value in (context or {}).items():
        result = result.replace('{' + key + '}', str(value))
    return result


def catalog_payload():
    """API-friendly snapshot of the versioned notification catalog."""
    return {
        'version': NOTIFICATION_CATALOG_VERSION,
        'channels': sorted(ALL_CHANNELS),
        'notification_types': [
            {
                'code': code,
                'event_name': spec['event_name'],
                'default_channel': spec['default_channel'],
                'statutory': spec['statutory'],
                'title_template': spec['title_template'],
                'message_template': spec['message_template'],
            }
            for code, spec in sorted(NOTIFICATION_DEFINITIONS.items())
        ],
    }


def validate_disabled_types(raw):
    """
    Return (normalized_list, errors).

    Statutory types cannot appear in disabled_types.
    """
    if raw is None:
        return [], []
    if not isinstance(raw, (list, tuple)):
        raise TypeError('disabled_types must be a list of notification type codes')
    unknown = []
    statutory = []
    normalized = []
    seen = set()
    for item in raw:
        if not isinstance(item, str) or not item:
            unknown.append(item)
            continue
        if item not in ALL_NOTIFICATION_TYPES:
            unknown.append(item)
            continue
        if item in STATUTORY_NOTIFICATION_TYPES:
            statutory.append(item)
            continue
        if item not in seen:
            seen.add(item)
            normalized.append(item)
    errors = []
    if unknown:
        errors.append(f'Unknown notification types: {unknown}')
    if statutory:
        errors.append(f'Statutory notification types cannot be disabled: {statutory}')
    return sorted(normalized), errors


def validate_channel(channel: str):
    if channel not in ALL_CHANNELS:
        raise ValueError(f'Unknown channel: {channel}')
    return channel
