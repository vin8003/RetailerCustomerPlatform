"""
OTP loyalty redeem (OE-220 / F-0107 slice B).

Extends CustomerLoyalty + Order.discount_from_points. Reuses generate_otp /
send_sms_otp. Does not add a second wallet or restaurant_points.
"""
import math
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from authentication.utils import generate_otp, send_sms_otp
from customers.models import CustomerLoyalty, LoyaltyRedeemOTP, LoyaltyTransaction
from orders.access import PERM_ORDERS_UPDATE, require_retailer_orders_access
from orders.models import Order
from retailers.models import RetailerCustomerMapping, RetailerRewardConfig
from retailers.module_flags import require_module_enabled

ERR_OTP_REQUIRED = 'OTP is required to redeem points'
ERR_OTP_INVALID = 'Invalid or expired OTP'
ERR_OTP_USED = 'This OTP has already been used'
ERR_NO_MOBILE = 'Customer has no registered mobile'
ERR_SEND_FAILED = 'Failed to send OTP'
ERR_NO_POINTS = 'No redeemable points'
ERR_ORDER_CLOSED = 'Order is not open for redeem'
ERR_ALREADY = 'Points already redeemed on this order'
ERR_NO_CUSTOMER = 'Order has no customer'
ERR_SPLIT_TENDER = 'Redeem is only allowed on a single-tender pending order'
ERR_NO_WALLET = 'No loyalty wallet at this shop'


def _retailer_only_response():
    return Response(
        {'error': 'Only retailers can access this endpoint'},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_staff_redeem_access(user):
    """Retailer JWT (403), rewards module, then orders.update + org locations."""
    if not user or not getattr(user, 'is_authenticated', False):
        return None, None, Response(
            {'error': 'Insufficient permissions for order operations'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if getattr(user, 'user_type', None) != 'retailer':
        return None, None, _retailer_only_response()
    _org, module_err = require_module_enabled(user, 'rewards')
    if module_err is not None:
        return None, None, module_err
    return require_retailer_orders_access(user, PERM_ORDERS_UPDATE)


def parse_requested_points(raw):
    """Return (Decimal-or-None, error). None means 'use the max allowed'."""
    if raw is None or raw == '':
        return None, None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None, ERR_NO_POINTS
    if value < 0:
        return None, ERR_NO_POINTS
    return value, None


def redeem_points_and_discount(total_amount, config, user_points, requested=None):
    """Whole-point redeem math used by checkout and staff redeem."""
    zero = Decimal('0')
    if not config or not config.is_active or user_points <= 0:
        return zero, Decimal('0.00')
    rate = config.conversion_rate
    if rate <= 0:
        return zero, Decimal('0.00')
    max_by_percent = (total_amount * config.max_reward_usage_percent) / Decimal('100')
    max_allowed_discount = min(total_amount, max_by_percent, config.max_reward_usage_flat)
    max_allowed_points = int(math.floor(max_allowed_discount / rate))
    available = int(math.floor(user_points))
    points = min(available, max_allowed_points)
    if requested is not None:
        points = min(points, int(math.floor(requested)))
    if points <= 0:
        return zero, Decimal('0.00')
    discount = Decimal(str(points)) * rate
    return Decimal(str(points)), discount


def _normalize_otp(otp_code):
    if otp_code is None:
        return ''
    return str(otp_code).strip()


def _latest_otp_qs(customer, retailer):
    return LoyaltyRedeemOTP.objects.filter(
        customer=customer,
        retailer=retailer,
    ).order_by('-created_at', '-id')


def _codes_match(stored, given):
    if stored is None or given is None:
        return False
    left = str(stored)
    right = _normalize_otp(given)
    if len(left) != len(right):
        return False
    return secrets.compare_digest(left, right)


def _evaluate_otp_row(row, otp_code):
    """Shared used / expired / attempts / match checks. May increment attempts."""
    code = _normalize_otp(otp_code)
    if code == '':
        return False, ERR_OTP_REQUIRED
    if row is None:
        return False, ERR_OTP_INVALID
    if row.is_used:
        return False, ERR_OTP_USED
    if row.is_expired():
        return False, ERR_OTP_INVALID
    if row.attempts >= settings.OTP_MAX_ATTEMPTS:
        return False, ERR_OTP_INVALID
    if not _codes_match(row.otp_code, code):
        row.attempts += 1
        row.save(update_fields=['attempts'])
        return False, ERR_OTP_INVALID
    return True, None


def peek_redeem_otp(customer, retailer, otp_code):
    """Check OTP without marking it used. Wrong code increments attempts."""
    if _normalize_otp(otp_code) == '':
        return False, ERR_OTP_REQUIRED
    row = _latest_otp_qs(customer, retailer).first()
    return _evaluate_otp_row(row, otp_code)


def consume_redeem_otp(customer, retailer, otp_code):
    """Mark a valid OTP used. Caller should be inside transaction.atomic()."""
    if _normalize_otp(otp_code) == '':
        return False, ERR_OTP_REQUIRED
    row = _latest_otp_qs(customer, retailer).select_for_update().first()
    ok, err = _evaluate_otp_row(row, otp_code)
    if not ok:
        return False, err
    row.is_used = True
    row.save(update_fields=['is_used'])
    return True, None


def issue_redeem_otp(customer, retailer):
    """
    Replace unused OTPs for this wallet and SMS the new code.
    Never log or return the code.
    """
    phone = (getattr(customer, 'phone_number', None) or '').strip()
    if not phone:
        return None, ERR_NO_MOBILE
    otp_code, _secret = generate_otp()
    expires_at = timezone.now() + timedelta(seconds=settings.OTP_EXPIRY_TIME)
    LoyaltyRedeemOTP.objects.filter(
        customer=customer, retailer=retailer, is_used=False
    ).delete()
    row = LoyaltyRedeemOTP.objects.create(
        customer=customer,
        retailer=retailer,
        otp_code=otp_code,
        expires_at=expires_at,
    )
    sent = send_sms_otp(phone, otp_code)
    if not sent and not settings.DEBUG:
        row.delete()
        return None, ERR_SEND_FAILED
    return row, None


def customer_has_wallet(customer, retailer):
    if CustomerLoyalty.objects.filter(customer=customer, retailer=retailer).exists():
        return True
    return RetailerCustomerMapping.objects.filter(
        customer=customer, retailer=retailer
    ).exists()


def _single_tender_field(order, old_total):
    tenders = (
        ('cash_amount', order.cash_amount),
        ('upi_amount', order.upi_amount),
        ('card_amount', order.card_amount),
        ('credit_amount', order.credit_amount),
    )
    nonzero = [name for name, amount in tenders if amount and amount > 0]
    matching = [name for name, amount in tenders if amount == old_total]
    if len(nonzero) == 1 and matching == nonzero:
        return nonzero[0]
    return None


def apply_pending_order_redeem(order, otp_code=None, requested_points=None):
    """
    Burn wallet points onto a pending order.
    Lock order + wallet, compute, consume OTP only if there is a burn.
    """
    requested, parse_err = parse_requested_points(requested_points)
    if parse_err:
        return None, parse_err

    with transaction.atomic():
        locked = (
            Order.objects.select_for_update()
            .select_related('customer', 'retailer')
            .get(pk=order.pk)
        )
        if locked.status != 'pending':
            return None, ERR_ORDER_CLOSED
        if locked.is_payment_locked:
            return None, ERR_ORDER_CLOSED
        if locked.points_redeemed and locked.points_redeemed > 0:
            return None, ERR_ALREADY
        if not locked.customer:
            return None, ERR_NO_CUSTOMER

        old_total = locked.total_amount
        tender_field = _single_tender_field(locked, old_total)
        if tender_field is None:
            return None, ERR_SPLIT_TENDER

        config = RetailerRewardConfig.objects.filter(retailer=locked.retailer).first()
        loyalty, _created = CustomerLoyalty.objects.select_for_update().get_or_create(
            customer=locked.customer,
            retailer=locked.retailer,
        )
        total_before = locked.subtotal + locked.delivery_fee - locked.discount_amount
        points, discount = redeem_points_and_discount(
            total_before, config, loyalty.points, requested=requested
        )
        if points <= 0:
            return None, ERR_NO_POINTS

        if config and config.is_active and config.otp_required_for_redeem:
            ok, err = consume_redeem_otp(locked.customer, locked.retailer, otp_code)
            if not ok:
                return None, err

        loyalty.points -= points
        loyalty.save(update_fields=['points'])
        LoyaltyTransaction.objects.create(
            customer=locked.customer,
            retailer=locked.retailer,
            amount=points,
            transaction_type='redeem',
            description=f"Redeemed on order #{locked.order_number}",
        )
        new_total = (total_before - discount).quantize(Decimal('0.01'))
        locked.discount_from_points = discount
        locked.points_redeemed = points
        locked.total_amount = new_total
        setattr(locked, tender_field, new_total)
        locked.save(update_fields=[
            'discount_from_points',
            'points_redeemed',
            'total_amount',
            tender_field,
        ])
    return locked, None


def staff_order_for_redeem(user, order_id):
    """Org-location scoped fetch (same tenant rule as get_order_for_retailer)."""
    _org, locations, err = require_staff_redeem_access(user)
    if err is not None:
        return None, err
    if not order_id:
        return None, Response(
            {'error': 'order_id is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    order = (
        Order.objects.select_related('customer', 'retailer')
        .filter(id=order_id, retailer__in=locations)
        .first()
    )
    if order is None:
        return None, Response(
            {'error': 'Order not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return order, None


def staff_customer_for_otp(user, data):
    """
    Resolve (customer, retailer) for a staff OTP send.
    Cross-tenant customer or location is 404.
    """
    org, locations, err = require_staff_redeem_access(user)
    if err is not None:
        return None, None, err

    order_id = data.get('order_id')
    if order_id:
        order, order_err = staff_order_for_redeem(user, order_id)
        if order_err is not None:
            return None, None, order_err
        if not order.customer:
            return None, None, Response(
                {'error': ERR_NO_CUSTOMER},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return order.customer, order.retailer, None

    location_id = data.get('location_id')
    customer_id = data.get('customer_id')
    if location_id is not None:
        retailer = locations.filter(id=location_id).first()
        if retailer is None:
            return None, None, Response(
                {'error': 'Invalid location for this organization'},
                status=status.HTTP_404_NOT_FOUND,
            )
    elif locations.count() == 1:
        retailer = locations.first()
    else:
        return None, None, Response(
            {'error': 'location_id is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not customer_id:
        return None, None, Response(
            {'error': 'customer_id is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    mapping = RetailerCustomerMapping.objects.filter(
        retailer__organization=org,
        retailer=retailer,
        customer_id=customer_id,
    ).select_related('customer').first()
    if mapping is None:
        return None, None, Response(
            {'error': 'Customer not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return mapping.customer, retailer, None


def otp_sent_payload():
    return {
        'message': 'OTP sent',
        'expires_in': settings.OTP_EXPIRY_TIME,
    }
