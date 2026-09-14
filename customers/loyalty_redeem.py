"""
OTP loyalty redeem (OE-220 / F-0107 slice B).

Extends CustomerLoyalty + Order.discount_from_points. Reuses generate_otp /
send_sms_otp. Does not add a second wallet or restaurant_points.
"""
import math
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from authentication.utils import generate_otp, send_sms_otp
from customers.models import CustomerLoyalty, LoyaltyRedeemOTP, LoyaltyTransaction
from orders.access import PERM_ORDERS_UPDATE, get_order_for_retailer, require_retailer_orders_access
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


def _retailer_only_response():
    return Response(
        {'error': 'Only retailers can access this endpoint'},
        status=status.HTTP_403_FORBIDDEN,
    )


def require_staff_redeem_access(user):
    """Retailer JWT first (403), then rewards module, then orders.update."""
    if not user or not getattr(user, 'is_authenticated', False):
        return None, Response(
            {'error': 'Insufficient permissions for order operations'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if getattr(user, 'user_type', None) != 'retailer':
        return None, _retailer_only_response()
    org, module_err = require_module_enabled(user, 'rewards')
    if module_err is not None:
        return None, module_err
    return org, None


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
        points = min(points, int(math.floor(Decimal(str(requested)))))
    if points <= 0:
        return zero, Decimal('0.00')
    discount = Decimal(str(points)) * rate
    return Decimal(str(points)), discount


def _active_otp_qs(customer, retailer):
    return LoyaltyRedeemOTP.objects.filter(
        customer=customer,
        retailer=retailer,
        is_used=False,
    ).order_by('-created_at', '-id')


def _codes_match(stored, given):
    if stored is None or given is None:
        return False
    left = str(stored)
    right = str(given)
    if len(left) != len(right):
        return False
    return secrets.compare_digest(left, right)


def peek_redeem_otp(customer, retailer, otp_code):
    """
    Check OTP without marking it used. Wrong code increments attempts.
    """
    if otp_code is None or str(otp_code).strip() == '':
        return False, ERR_OTP_REQUIRED
    row = _active_otp_qs(customer, retailer).first()
    if row is None:
        return False, ERR_OTP_INVALID
    if row.is_expired():
        return False, ERR_OTP_INVALID
    if row.attempts >= settings.OTP_MAX_ATTEMPTS:
        return False, ERR_OTP_INVALID
    if not _codes_match(row.otp_code, otp_code):
        row.attempts += 1
        row.save(update_fields=['attempts'])
        return False, ERR_OTP_INVALID
    return True, None


def consume_redeem_otp(customer, retailer, otp_code):
    """Mark a valid OTP used. Caller should be inside transaction.atomic()."""
    if otp_code is None or str(otp_code).strip() == '':
        return False, ERR_OTP_REQUIRED
    row = _active_otp_qs(customer, retailer).select_for_update().first()
    if row is None:
        return False, ERR_OTP_INVALID
    if timezone.now() > row.expires_at:
        return False, ERR_OTP_INVALID
    if row.is_used:
        return False, ERR_OTP_USED
    if row.attempts >= settings.OTP_MAX_ATTEMPTS:
        return False, ERR_OTP_INVALID
    if not _codes_match(row.otp_code, otp_code):
        row.attempts += 1
        row.save(update_fields=['attempts'])
        return False, ERR_OTP_INVALID
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
    _active_otp_qs(customer, retailer).delete()
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


def apply_pending_order_redeem(order, otp_code=None, requested_points=None):
    """
    Burn wallet points onto a pending/confirmed order.
    OTP is consumed in the same transaction as the burn.
    """
    if order.status not in ('pending', 'confirmed'):
        return None, ERR_ORDER_CLOSED
    if order.points_redeemed and order.points_redeemed > 0:
        return None, ERR_ALREADY
    if not order.customer:
        return None, ERR_NO_CUSTOMER

    config = RetailerRewardConfig.objects.filter(retailer=order.retailer).first()
    with transaction.atomic():
        if config and config.is_active and config.otp_required_for_redeem:
            ok, err = consume_redeem_otp(order.customer, order.retailer, otp_code)
            if not ok:
                return None, err

        loyalty, _created = CustomerLoyalty.objects.select_for_update().get_or_create(
            customer=order.customer,
            retailer=order.retailer,
        )
        total_before = (
            order.subtotal + order.delivery_fee - order.discount_amount
        )
        points, discount = redeem_points_and_discount(
            total_before, config, loyalty.points, requested=requested_points
        )
        if points <= 0:
            return None, ERR_NO_POINTS

        loyalty.points -= points
        loyalty.save(update_fields=['points'])
        LoyaltyTransaction.objects.create(
            customer=order.customer,
            retailer=order.retailer,
            amount=points,
            transaction_type='redeem',
            description=f"Redeemed on order #{order.order_number}",
        )
        old_total = order.total_amount
        new_total = (total_before - discount).quantize(Decimal('0.01'))
        order.discount_from_points = discount
        order.points_redeemed = points
        order.total_amount = new_total
        update_fields = ['discount_from_points', 'points_redeemed', 'total_amount']
        if order.cash_amount == old_total:
            order.cash_amount = new_total
            update_fields.append('cash_amount')
        elif order.upi_amount == old_total:
            order.upi_amount = new_total
            update_fields.append('upi_amount')
        order.save(update_fields=update_fields)
    return order, None


def staff_order_for_redeem(user, order_id):
    _org, err = require_staff_redeem_access(user)
    if err is not None:
        return None, err
    _org, locations, loc_err = require_retailer_orders_access(user, PERM_ORDERS_UPDATE)
    if loc_err is not None:
        return None, loc_err
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
    org, err = require_staff_redeem_access(user)
    if err is not None:
        return None, None, err

    order_id = data.get('order_id')
    if order_id:
        order, order_err = get_order_for_retailer(user, order_id, PERM_ORDERS_UPDATE)
        if order_err is not None:
            return None, None, order_err
        if not order.customer:
            return None, None, Response(
                {'error': ERR_NO_CUSTOMER},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return order.customer, order.retailer, None

    _org, locations, loc_err = require_retailer_orders_access(user, PERM_ORDERS_UPDATE)
    if loc_err is not None:
        return None, None, loc_err

    location_id = data.get('location_id')
    customer_id = data.get('customer_id')
    if location_id is not None:
        retailer = locations.filter(id=location_id).first()
        if retailer is None:
            return None, None, Response(
                {'error': 'Order not found'},
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
