"""
Distance-based delivery pricing and serviceability.

One place decides, for a shop and a drop point, whether the shop delivers there
and what the delivery fee is. Order placement, order modification, the
checkout quote endpoint and shop discovery all call it, so the fee a customer
is shown is the fee the order is created with.

Fee modes (RetailerProfile.delivery_fee_mode):

- ``flat``: the old behaviour. ``delivery_charge`` for every delivery.
- ``distance``: ``delivery_fee_tiers`` is a list of ``{"up_to_km", "fee"}``
  bands, matched inclusively in ascending order. Past the last band the fee is
  the last band's fee plus ``delivery_fee_per_km`` for every started km beyond
  it (no per-km rate means the last band's fee holds up to the radius).

In both modes ``free_delivery_threshold`` still makes the delivery free for an
order at or above it, and ``delivery_radius`` (km, straight-line haversine)
caps where the shop delivers.

When the shop or the drop point has no coordinates, distance cannot be known:
the shop is treated as before this feature (pincode/city discovery, no radius
check at checkout) and charges the flat ``delivery_charge``.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

FEE_MODE_FLAT = 'flat'
FEE_MODE_DISTANCE = 'distance'

DEFAULT_RADIUS_KM = Decimal('5')
MAX_TIERS = 10
MAX_TIER_KM = Decimal('500')
MAX_FEE = Decimal('100000')

_CENT = Decimal('0.01')
_ZERO = Decimal('0.00')


def _money(value) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in km between two WGS84 points."""
    r = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = p2 - p1
    dlmb = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def has_coordinates(lat, lng) -> bool:
    """
    True when lat/lng look like a real pin. 0,0 (and None) is what forms send
    when nobody picked a location, so it never counts.
    """
    if lat is None or lng is None:
        return False
    try:
        flat, flng = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(flat) and math.isfinite(flng)):
        return False
    if not (-90 <= flat <= 90 and -180 <= flng <= 180):
        return False
    return not (abs(flat) < 1e-6 and abs(flng) < 1e-6)


def retailer_distance_km(retailer, lat, lng) -> Optional[float]:
    """Distance from the shop to a point, or None when either side has no pin."""
    if not (has_coordinates(retailer.latitude, retailer.longitude) and has_coordinates(lat, lng)):
        return None
    return haversine_km(retailer.latitude, retailer.longitude, lat, lng)


def effective_radius_km(radius) -> Decimal:
    """A radius of 0 or blank has always meant the 5 km default in discovery."""
    try:
        value = Decimal(str(radius)) if radius is not None else Decimal('0')
    except (InvalidOperation, ValueError):
        value = Decimal('0')
    return value if value > 0 else DEFAULT_RADIUS_KM


def within_radius(retailer, distance_km: Optional[float]) -> bool:
    """Whether a known distance is inside the shop's delivery radius (inclusive)."""
    if distance_km is None:
        return True
    return Decimal(str(distance_km)) <= effective_radius_km(retailer.delivery_radius)


# ---------------------------------------------------------------------------
# Tier config parsing / validation (shared with the profile serializer)
# ---------------------------------------------------------------------------

class TierConfigError(ValueError):
    pass


def _decimal_field(raw, name, index) -> Decimal:
    if isinstance(raw, bool) or raw is None or raw == '':
        raise TierConfigError(f'Tier {index}: {name} is required.')
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise TierConfigError(f'Tier {index}: {name} must be a number.')
    if not value.is_finite():
        raise TierConfigError(f'Tier {index}: {name} must be a number.')
    return value


def normalize_tiers(raw) -> list[dict]:
    """
    Validate a tier list from the retailer panel and return it in canonical
    form: ascending ``up_to_km`` (2 dp), ``fee`` as a 2 dp string.

    Accepts a list or its JSON string (multipart forms send strings).
    """
    if raw in (None, ''):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise TierConfigError('Delivery fee tiers must be a JSON list.')
    if not isinstance(raw, list):
        raise TierConfigError('Delivery fee tiers must be a list.')
    if len(raw) > MAX_TIERS:
        raise TierConfigError(f'At most {MAX_TIERS} delivery fee tiers are allowed.')

    tiers = []
    for i, tier in enumerate(raw, start=1):
        if not isinstance(tier, dict):
            raise TierConfigError(f'Tier {i} must be an object with up_to_km and fee.')
        up_to = _decimal_field(tier.get('up_to_km'), 'up_to_km', i)
        fee = _decimal_field(tier.get('fee'), 'fee', i)
        if up_to <= 0 or up_to > MAX_TIER_KM:
            raise TierConfigError(f'Tier {i}: up_to_km must be more than 0 and at most {MAX_TIER_KM}.')
        if fee < 0 or fee > MAX_FEE:
            raise TierConfigError(f'Tier {i}: fee must be between 0 and {MAX_FEE}.')
        tiers.append({'up_to_km': up_to.quantize(_CENT), 'fee': _money(fee)})

    tiers.sort(key=lambda t: t['up_to_km'])
    for a, b in zip(tiers, tiers[1:]):
        if a['up_to_km'] == b['up_to_km']:
            raise TierConfigError(f'Two tiers end at {a["up_to_km"]} km.')

    return [{'up_to_km': str(t['up_to_km']), 'fee': str(t['fee'])} for t in tiers]


def _parsed_tiers(retailer) -> list[tuple[Decimal, Decimal]]:
    """Stored tiers as (up_to_km, fee) pairs; tolerant of hand-edited rows."""
    out = []
    raw = retailer.delivery_fee_tiers or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    if not isinstance(raw, list):
        return out
    for tier in raw:
        if not isinstance(tier, dict):
            continue
        try:
            up_to = Decimal(str(tier.get('up_to_km')))
            fee = Decimal(str(tier.get('fee')))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if up_to.is_finite() and fee.is_finite() and up_to > 0 and fee >= 0:
            out.append((up_to, fee))
    out.sort(key=lambda t: t[0])
    return out


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

@dataclass
class DeliveryQuote:
    deliverable: bool
    fee: Decimal = _ZERO
    base_fee: Decimal = _ZERO  # before the free-delivery threshold
    distance_km: Optional[Decimal] = None
    fee_mode: str = FEE_MODE_FLAT
    pricing: str = 'flat'  # flat | tier | per_km | fallback_flat
    free_delivery_applied: bool = False
    reason: str = ''
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            'deliverable': self.deliverable,
            'delivery_fee': str(self.fee),
            'fee_before_free_delivery': str(self.base_fee),
            'distance_km': str(self.distance_km) if self.distance_km is not None else None,
            'fee_mode': self.fee_mode,
            'pricing': self.pricing,
            'free_delivery_applied': self.free_delivery_applied,
            'reason': self.reason,
        }


def distance_fee(retailer, distance_km) -> tuple[Decimal, str]:
    """Fee before the free-delivery threshold for a known distance (distance mode)."""
    tiers = _parsed_tiers(retailer)
    per_km = Decimal(retailer.delivery_fee_per_km or 0)
    d = Decimal(str(distance_km))

    for up_to, fee in tiers:
        if d <= up_to:
            return _money(fee), 'tier'

    if tiers:
        last_up_to, last_fee = tiers[-1]
    else:
        # No bands: delivery_charge is the base, per-km counts from the shop.
        last_up_to, last_fee = Decimal('0'), Decimal(retailer.delivery_charge or 0)

    if per_km > 0:
        # Every started km past the last band is charged (2.1 km over -> 3 km).
        extra_km = Decimal(math.ceil(d - last_up_to))
        return _money(last_fee + extra_km * per_km), 'per_km'
    return _money(last_fee), 'tier' if tiers else 'flat'


def quote_delivery(retailer, lat=None, lng=None, order_total=None, check_serviceable=True) -> DeliveryQuote:
    """
    Delivery decision for a shop and a drop point.

    ``order_total`` is the amount compared with ``free_delivery_threshold``
    (callers pass the same basis they always have). None skips the threshold.
    ``check_serviceable=False`` prices without the offers_delivery / radius
    checks (re-pricing an order the shop already accepted).
    """
    mode = retailer.delivery_fee_mode or FEE_MODE_FLAT

    if check_serviceable and not retailer.offers_delivery:
        return DeliveryQuote(False, fee_mode=mode, reason='This retailer does not offer delivery.')

    distance = retailer_distance_km(retailer, lat, lng)
    distance_dec = (
        Decimal(str(distance)).quantize(_CENT, rounding=ROUND_HALF_UP)
        if distance is not None else None
    )

    # Pricing and the radius use the distance as shown (to 10 m), so a pin
    # stored to 8 decimals never tips 6.00 km into the 7th km.
    if check_serviceable and distance_dec is not None and not within_radius(retailer, distance_dec):
        return DeliveryQuote(
            False,
            distance_km=distance_dec,
            fee_mode=mode,
            pricing='',
            reason=(
                f'This address is {distance_dec} km away; '
                f'the shop delivers within {effective_radius_km(retailer.delivery_radius).normalize():f} km.'
            ),
        )

    if mode == FEE_MODE_DISTANCE and distance_dec is not None:
        base, pricing = distance_fee(retailer, distance_dec)
    else:
        base = _money(retailer.delivery_charge or 0)
        pricing = 'fallback_flat' if mode == FEE_MODE_DISTANCE else 'flat'

    fee = base
    free_applied = False
    threshold = Decimal(retailer.free_delivery_threshold or 0)
    if base > 0 and threshold > 0 and order_total is not None and Decimal(order_total) >= threshold:
        fee = _ZERO
        free_applied = True

    return DeliveryQuote(
        True,
        fee=fee,
        base_fee=base,
        distance_km=distance_dec,
        fee_mode=mode,
        pricing=pricing,
        free_delivery_applied=free_applied,
    )


def quote_for_address(retailer, address, order_total=None, check_serviceable=True) -> DeliveryQuote:
    lat = getattr(address, 'latitude', None) if address is not None else None
    lng = getattr(address, 'longitude', None) if address is not None else None
    return quote_delivery(
        retailer, lat, lng, order_total=order_total, check_serviceable=check_serviceable
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def retailer_ids_within_radius(queryset, lat, lng) -> tuple[list[int], dict[int, float]]:
    """
    Ids of shops in ``queryset`` that have coordinates and whose delivery
    radius covers (lat, lng), with each one's distance.
    """
    ids, distances = [], {}
    rows = queryset.exclude(latitude__isnull=True).exclude(longitude__isnull=True).values_list(
        'id', 'latitude', 'longitude', 'delivery_radius'
    )
    for rid, rlat, rlng, radius in rows:
        if not has_coordinates(rlat, rlng):
            continue
        d = haversine_km(rlat, rlng, lat, lng)
        if Decimal(str(d)).quantize(_CENT, rounding=ROUND_HALF_UP) <= effective_radius_km(radius):
            ids.append(rid)
            distances[rid] = d
    return ids, distances


def serves_pincode(shop_pincode, serviceable_pincodes, user_pincode) -> bool:
    """The pre-radius rule: the shop's own pincode or one it lists as serviceable."""
    if shop_pincode == user_pincode:
        return True
    if isinstance(serviceable_pincodes, str):
        return serviceable_pincodes == user_pincode
    if isinstance(serviceable_pincodes, list):
        return user_pincode in [str(p).strip() for p in serviceable_pincodes]
    return False


def retailer_ids_without_coordinates(queryset, user_pincode=None) -> list[int]:
    """
    Shops with no usable pin; discovery falls back to pincode/city for them.
    With ``user_pincode`` only the shops serving that pincode are returned.
    """
    out = []
    rows = queryset.values_list('id', 'latitude', 'longitude', 'pincode', 'serviceable_pincodes')
    for rid, rlat, rlng, shop_pin, serviceable in rows:
        if has_coordinates(rlat, rlng):
            continue
        if user_pincode and not serves_pincode(shop_pin, serviceable, user_pincode):
            continue
        out.append(rid)
    return out
