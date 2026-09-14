"""
OE-220 / F-0107 — OTP loyalty redeem (thin slice B).

Earn-on-sale already exists on POS finalize / delivered. This file locks
the missing OTP burn: without OTP when mode is on, redeem fails and the
wallet is unchanged. Valid OTP burns CustomerLoyalty and writes
Order.discount_from_points. No restaurant_points, no second wallet.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from cart.models import Cart, CartItem
from customers.models import CustomerLoyalty, CustomerProfile, LoyaltyRedeemOTP
from orders.models import Order
from orders.serializers import OrderCreateSerializer
from products.models import Product, ProductBrand, ProductCategory
from retailers.models import (
    OrgRole,
    OrgStaffMembership,
    RetailerCustomerMapping,
    RetailerProfile,
    RetailerRewardConfig,
)
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import ROLE_SLUG_CASHIER


def _make_retailer(username, shop_name):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    profile = RetailerProfile.objects.create(
        user=user,
        shop_name=shop_name,
        address_line1="1 Main",
        city="City",
        state="State",
        pincode="110001",
        is_active=True,
    )
    ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_staff(org, username, permissions):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    role = OrgRole.objects.create(
        organization=org,
        slug=f"role_{username}",
        name=f"Role {username}",
        permissions=list(permissions),
        is_system=False,
    )
    OrgStaffMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_active=True,
    )
    return user


def _make_customer(username, phone):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        phone_number=phone,
        is_active=True,
        is_phone_verified=True,
        registration_status="registered",
    )
    CustomerProfile.objects.create(user=user)
    return user


def _product(retailer, price=Decimal("100.00")):
    category = ProductCategory.objects.create(name="Cat", retailer=retailer)
    brand = ProductBrand.objects.create(name="Brand")
    return Product.objects.create(
        retailer=retailer,
        name="Widget",
        category=category,
        brand=brand,
        price=price,
        quantity=50,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def _reward_config(retailer, **kwargs):
    defaults = {
        "is_active": True,
        "otp_required_for_redeem": True,
        "conversion_rate": Decimal("1.00"),
        "max_reward_usage_percent": Decimal("50.00"),
        "max_reward_usage_flat": Decimal("50.00"),
    }
    defaults.update(kwargs)
    return RetailerRewardConfig.objects.create(retailer=retailer, **defaults)


def _pending_order(customer, retailer, product, total=Decimal("100.00")):
    return Order.objects.create(
        customer=customer,
        retailer=retailer,
        delivery_mode="pickup",
        payment_mode="cash",
        subtotal=total,
        total_amount=total,
        cash_amount=total,
        status="pending",
        source="app",
        payment_status="pending_payment",
    )


def _issue_otp(customer, retailer, code="123456"):
    from django.conf import settings
    from django.utils import timezone

    LoyaltyRedeemOTP.objects.filter(
        customer=customer, retailer=retailer, is_used=False
    ).delete()
    return LoyaltyRedeemOTP.objects.create(
        customer=customer,
        retailer=retailer,
        otp_code=code,
        expires_at=timezone.now() + timezone.timedelta(seconds=settings.OTP_EXPIRY_TIME),
    )


STAFF_REDEEM_URL = "staff_loyalty_redeem"
STAFF_OTP_URL = "staff_loyalty_redeem_otp"
CUSTOMER_OTP_URL = "customer_loyalty_redeem_otp"
CONFIG_URL = "manage_reward_configuration"


@pytest.mark.django_db
class TestCheckoutRedeemRequiresOtp:
    def _checkout(self, customer, retailer, product, otp=None):
        from customers.models import CustomerAddress

        Cart.objects.filter(customer=customer, retailer=retailer).delete()
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(
            cart=cart, product=product, quantity=1, unit_price=product.price
        )
        addr = CustomerAddress.objects.create(
            customer=customer, address_line1="1 Test", is_active=True
        )
        data = {
            "retailer_id": retailer.id,
            "use_reward_points": True,
            "delivery_mode": "pickup",
            "payment_mode": "cash",
            "address_id": addr.id,
        }
        if otp is not None:
            data["redeem_otp"] = otp
        request = MagicMock()
        request.user = customer
        serializer = OrderCreateSerializer(
            data=data, context={"request": request, "customer": customer}
        )
        return serializer

    def test_redeem_without_otp_fails_when_otp_mode_on(self):
        _owner, retailer = _make_retailer("oe220_chk_owner", "OE220 Checkout Shop")
        local = _product(retailer)
        customer = _make_customer("oe220_chk_cust", "9000002201")
        _reward_config(retailer)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )

        serializer = self._checkout(customer, retailer, local)
        assert serializer.is_valid() is False
        assert "redeem_otp" in serializer.errors
        loyalty.refresh_from_db()
        assert loyalty.points == Decimal("80.00")
        assert Order.objects.filter(customer=customer, retailer=retailer).count() == 0

    def test_wrong_otp_does_not_burn_points(self):
        _owner, retailer = _make_retailer("oe220_chk_bad", "OE220 Bad OTP Shop")
        local = _product(retailer)
        customer = _make_customer("oe220_chk_bad_cust", "9000002202")
        _reward_config(retailer)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        _issue_otp(customer, retailer, "111111")

        serializer = self._checkout(customer, retailer, local, otp="000000")
        assert serializer.is_valid() is False
        loyalty.refresh_from_db()
        assert loyalty.points == Decimal("80.00")
        otp = LoyaltyRedeemOTP.objects.get(customer=customer, retailer=retailer)
        assert otp.is_used is False
        assert Order.objects.filter(customer=customer, retailer=retailer).count() == 0

    def test_valid_otp_burns_and_sets_discount_from_points(self):
        _owner, retailer = _make_retailer("oe220_chk_ok", "OE220 OK OTP Shop")
        local = _product(retailer, price=Decimal("100.00"))
        customer = _make_customer("oe220_chk_ok_cust", "9000002203")
        _reward_config(retailer, max_reward_usage_flat=Decimal("50.00"))
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        _issue_otp(customer, retailer, "654321")

        serializer = self._checkout(customer, retailer, local, otp="654321")
        assert serializer.is_valid(), serializer.errors
        order = serializer.save()
        loyalty.refresh_from_db()
        assert order.discount_from_points == Decimal("50.00")
        assert order.points_redeemed == Decimal("50.00")
        assert loyalty.points == Decimal("30.00")
        otp = LoyaltyRedeemOTP.objects.get(customer=customer, retailer=retailer)
        assert otp.is_used is True

    def test_used_otp_cannot_be_reused(self):
        _owner, retailer = _make_retailer("oe220_chk_reuse", "OE220 Reuse Shop")
        local = _product(retailer)
        customer = _make_customer("oe220_chk_reuse_cust", "9000002204")
        _reward_config(retailer)
        CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        _issue_otp(customer, retailer, "222222")

        first = self._checkout(customer, retailer, local, otp="222222")
        assert first.is_valid(), first.errors
        first.save()

        second = self._checkout(customer, retailer, local, otp="222222")
        assert second.is_valid() is False
        assert Order.objects.filter(customer=customer, retailer=retailer).count() == 1

    def test_otp_mode_off_still_redeems_without_code(self):
        _owner, retailer = _make_retailer("oe220_chk_off", "OE220 OTP Off Shop")
        local = _product(retailer, price=Decimal("100.00"))
        customer = _make_customer("oe220_chk_off_cust", "9000002205")
        _reward_config(retailer, otp_required_for_redeem=False)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )

        serializer = self._checkout(customer, retailer, local)
        assert serializer.is_valid(), serializer.errors
        order = serializer.save()
        loyalty.refresh_from_db()
        assert order.discount_from_points == Decimal("50.00")
        assert loyalty.points == Decimal("30.00")


@pytest.mark.django_db
class TestStaffRedeemEndpoint:
    def test_redeem_without_otp_fails_when_mode_on(self, api_client):
        owner, retailer = _make_retailer("oe220_st_owner", "OE220 Staff Shop")
        customer = _make_customer("oe220_st_cust", "9000002211")
        product = _product(retailer)
        _reward_config(retailer)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        order = _pending_order(customer, retailer, product)
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=customer)

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse(STAFF_REDEEM_URL),
            {"order_id": order.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        loyalty.refresh_from_db()
        order.refresh_from_db()
        assert loyalty.points == Decimal("80.00")
        assert order.discount_from_points == Decimal("0.00")
        assert order.points_redeemed == Decimal("0.00")
        assert order.total_amount == Decimal("100.00")

    def test_valid_otp_burns_and_applies_discount(self, api_client):
        owner, retailer = _make_retailer("oe220_st_ok", "OE220 Staff OK")
        customer = _make_customer("oe220_st_ok_cust", "9000002212")
        product = _product(retailer)
        _reward_config(retailer)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        order = _pending_order(customer, retailer, product)
        _issue_otp(customer, retailer, "333333")

        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse(STAFF_REDEEM_URL),
            {"order_id": order.id, "otp_code": "333333"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "otp_code" not in resp.data
        assert "333333" not in str(resp.data)
        loyalty.refresh_from_db()
        order.refresh_from_db()
        assert order.discount_from_points == Decimal("50.00")
        assert order.points_redeemed == Decimal("50.00")
        assert order.total_amount == Decimal("50.00")
        assert loyalty.points == Decimal("30.00")

    def test_customer_cannot_call_staff_redeem(self, api_client):
        _owner, retailer = _make_retailer("oe220_st_403", "OE220 Staff 403")
        customer = _make_customer("oe220_st_403_cust", "9000002213")
        product = _product(retailer)
        _reward_config(retailer)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        order = _pending_order(customer, retailer, product)
        _issue_otp(customer, retailer, "444444")

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse(STAFF_REDEEM_URL),
            {"order_id": order.id, "otp_code": "444444"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        loyalty.refresh_from_db()
        order.refresh_from_db()
        assert loyalty.points == Decimal("80.00")
        assert order.discount_from_points == Decimal("0.00")

    def test_cashier_without_orders_update_is_403(self, api_client):
        owner, retailer = _make_retailer("oe220_st_cash", "OE220 Cashier Shop")
        customer = _make_customer("oe220_st_cash_cust", "9000002214")
        product = _product(retailer)
        _reward_config(retailer)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        order = _pending_order(customer, retailer, product)
        _issue_otp(customer, retailer, "555555")
        staff = _make_staff(retailer.organization, "oe220_cashier", [])
        cashier_role = OrgRole.objects.get(
            organization=retailer.organization, slug=ROLE_SLUG_CASHIER
        )
        assert "orders.update" not in (cashier_role.permissions or [])

        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse(STAFF_REDEEM_URL),
            {"order_id": order.id, "otp_code": "555555"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        loyalty.refresh_from_db()
        order.refresh_from_db()
        assert loyalty.points == Decimal("80.00")
        assert order.discount_from_points == Decimal("0.00")
        assert owner.username == "oe220_st_cash"

    def test_cross_tenant_redeem_is_404(self, api_client):
        _owner_a, retailer_a = _make_retailer("oe220_st_a", "OE220 Tenant A")
        owner_b, _retailer_b = _make_retailer("oe220_st_b", "OE220 Tenant B")
        customer = _make_customer("oe220_st_shared", "9000002215")
        product = _product(retailer_a)
        _reward_config(retailer_a)
        loyalty = CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer_a, points=Decimal("80.00")
        )
        order = _pending_order(customer, retailer_a, product)
        _issue_otp(customer, retailer_a, "666666")

        api_client.force_authenticate(user=owner_b)
        resp = api_client.post(
            reverse(STAFF_REDEEM_URL),
            {"order_id": order.id, "otp_code": "666666"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        loyalty.refresh_from_db()
        order.refresh_from_db()
        assert loyalty.points == Decimal("80.00")
        assert order.discount_from_points == Decimal("0.00")

    def test_staff_redeem_query_budget(self, api_client, django_assert_num_queries):
        owner, retailer = _make_retailer("oe220_st_q", "OE220 Query Shop")
        customer = _make_customer("oe220_st_q_cust", "9000002216")
        product = _product(retailer)
        _reward_config(retailer)
        CustomerLoyalty.objects.create(
            customer=customer, retailer=retailer, points=Decimal("80.00")
        )
        order = _pending_order(customer, retailer, product)
        _issue_otp(customer, retailer, "777777")

        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(25):
            resp = api_client.post(
                reverse(STAFF_REDEEM_URL),
                {"order_id": order.id, "otp_code": "777777"},
                format="json",
            )
        assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestRequestRedeemOtp:
    @patch("customers.loyalty_redeem.send_sms_otp", return_value=True)
    def test_customer_request_does_not_return_secret(self, _mock_sms, api_client):
        _owner, retailer = _make_retailer("oe220_otp_owner", "OE220 OTP Shop")
        customer = _make_customer("oe220_otp_cust", "9000002221")
        _reward_config(retailer)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse(CUSTOMER_OTP_URL),
            {"retailer_id": retailer.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert "otp_code" not in resp.data
        row = LoyaltyRedeemOTP.objects.get(customer=customer, retailer=retailer)
        assert row.otp_code
        assert row.otp_code not in str(resp.data)

    def test_customer_cannot_request_staff_otp(self, api_client):
        _owner, retailer = _make_retailer("oe220_otp_403", "OE220 OTP 403")
        customer = _make_customer("oe220_otp_403_cust", "9000002222")
        _reward_config(retailer)

        api_client.force_authenticate(user=customer)
        resp = api_client.post(
            reverse(STAFF_OTP_URL),
            {"customer_id": customer.id, "location_id": retailer.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_staff_cannot_request_otp_for_other_tenant(self, api_client):
        _owner_a, retailer_a = _make_retailer("oe220_otp_a", "OE220 OTP A")
        owner_b, _retailer_b = _make_retailer("oe220_otp_b", "OE220 OTP B")
        customer = _make_customer("oe220_otp_x", "9000002223")
        _reward_config(retailer_a)
        RetailerCustomerMapping.objects.create(retailer=retailer_a, customer=customer)

        api_client.force_authenticate(user=owner_b)
        resp = api_client.post(
            reverse(STAFF_OTP_URL),
            {"customer_id": customer.id, "location_id": retailer_a.id},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert LoyaltyRedeemOTP.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
class TestRewardConfigOtpFlagAuth:
    def test_customer_cannot_mutate_otp_flag(self, api_client):
        owner, retailer = _make_retailer("oe220_cfg_owner", "OE220 Config Shop")
        customer = _make_customer("oe220_cfg_cust", "9000002231")
        config = _reward_config(retailer, otp_required_for_redeem=True)

        api_client.force_authenticate(user=customer)
        resp = api_client.put(
            reverse(CONFIG_URL),
            {"otp_required_for_redeem": False},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        config.refresh_from_db()
        assert config.otp_required_for_redeem is True
        assert owner.username == "oe220_cfg_owner"

    def test_cross_tenant_put_does_not_mutate_other_config(self, api_client):
        _owner_a, retailer_a = _make_retailer("oe220_cfg_a", "OE220 Cfg A")
        owner_b, retailer_b = _make_retailer("oe220_cfg_b", "OE220 Cfg B")
        config_a = _reward_config(retailer_a, otp_required_for_redeem=True)
        _reward_config(retailer_b, otp_required_for_redeem=False)

        api_client.force_authenticate(user=owner_b)
        resp = api_client.put(
            reverse(CONFIG_URL),
            {"otp_required_for_redeem": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        config_a.refresh_from_db()
        assert config_a.otp_required_for_redeem is True
        config_b = RetailerRewardConfig.objects.get(retailer=retailer_b)
        assert config_b.otp_required_for_redeem is True
