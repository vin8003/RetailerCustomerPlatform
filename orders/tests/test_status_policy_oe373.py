import pytest

from orders.domain.status_policy import InvalidStatusTransitionError, ensure_transition_allowed


def test_confirmed_can_go_straight_to_packed():
    # OE-373: the retailer UI offers Confirmed -> Packed.
    ensure_transition_allowed('confirmed', 'packed')


def test_confirmed_still_cannot_skip_to_delivery():
    with pytest.raises(InvalidStatusTransitionError):
        ensure_transition_allowed('confirmed', 'out_for_delivery')
