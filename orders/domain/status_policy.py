"""Order status transition policy."""

ALLOWED_STATUS_TRANSITIONS = {
    'pending': ['confirmed', 'cancelled', 'waiting_for_customer_approval'],
    'waiting_for_customer_approval': ['confirmed', 'cancelled', 'pending'],
    'confirmed': ['processing', 'cancelled'],
    'processing': ['packed', 'cancelled'],
    'packed': ['out_for_delivery', 'delivered'],
    'out_for_delivery': ['delivered', 'cancelled'],
    'delivered': ['returned'],
    'cancelled': [],
    'returned': [],
}


class InvalidStatusTransitionError(ValueError):
    """Raised when attempting to transition order to a disallowed status."""



def ensure_transition_allowed(current_status: str, new_status: str) -> None:
    """Validate and guard status transitions."""
    if new_status not in ALLOWED_STATUS_TRANSITIONS.get(current_status, []):
        raise InvalidStatusTransitionError(
            f"Cannot change status from '{current_status}' to '{new_status}'"
        )
