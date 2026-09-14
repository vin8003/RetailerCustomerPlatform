"""
OE-143 / F-0052 — Khata credit limit and due-days lock.

Covers: limit block, due-days lock, override + audit, pay-while-locked,
unauthorized 403, cross-tenant deny, POS credit finalize query budget.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from authentication.models import User
from orders.models import Order
from products.models import Product, ProductBrand, ProductCategory
from retailers.credit_lock import (
    PERM_CREDIT_OVERRIDE,
    REASON_CREDIT_LIMIT,
    REASON_CREDIT_OVERDUE,
    credit_sale_lock_reasons,
    is_credit_override_requested,
)
from retailers.models import (
    CustomerLedger,
    OrgAuditLog,
    OrgRole,
    OrgStaffMembership,
    RetailerCustomerMapping,
    RetailerProfile,
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


def _make_customer(username, phone="9988776655"):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        phone_number=phone,
        is_active=True,
        is_phone_verified=True,
    )


def _product(retailer, price=Decimal("100.00")):
    category = ProductCategory.objects.create(name="Cat", retailer=retailer)
    brand = ProductBrand.objects.create(name="Brand")
    return Product.objects.create(
        retailer=retailer,
        name="Widget",
        category=category,
        brand=brand,
        price=price,
        quantity=100,
        track_inventory=True,
        is_active=True,
        is_available=True,
        unit="piece",
    )


def _pos_credit_payload(product, customer_mobile, credit_amount, *, override=False):
    amount = float(credit_amount)
    payload = {
        "items": [
            {
                "product_id": product.id,
                "quantity": 1,
                "unit_price": str(product.price),
            }
        ],
        "subtotal": amount,
        "total_amount": amount,
        "customer_mobile": customer_mobile,
        "payment_details": {"credit": amount},
    }
    if override:
        payload["credit_override"] = True
    return payload


@pytest.mark.django_db
class TestCreditLockHelpers:
    def test_limit_and_due_days_reasons(self):
        now = timezone.now()
        mapping = SimpleNamespace(
            credit_limit=Decimal("100.00"),
            current_balance=Decimal("80.00"),
            credit_due_days=7,
            outstanding_since=now - timedelta(days=10),
        )
        reasons = credit_sale_lock_reasons(mapping, Decimal("30.00"), now=now)
        assert REASON_CREDIT_LIMIT in reasons
        assert REASON_CREDIT_OVERDUE in reasons

    def test_null_due_days_and_zero_limit_are_unset(self):
        now = timezone.now()
        mapping = SimpleNamespace(
            credit_limit=Decimal("0.00"),
            current_balance=Decimal("500.00"),
            credit_due_days=None,
            outstanding_since=now - timedelta(days=40),
        )
        assert credit_sale_lock_reasons(mapping, Decimal("50.00"), now=now) == []

    def test_due_days_lock_requires_outstanding(self):
        now = timezone.now()
        mapping = SimpleNamespace(
            credit_limit=Decimal("0.00"),
            current_balance=Decimal("0.00"),
            credit_due_days=7,
            outstanding_since=None,
        )
        assert credit_sale_lock_reasons(mapping, Decimal("50.00"), now=now) == []

    def test_override_flag_parsing(self):
        assert is_credit_override_requested({"credit_override": True})
        assert is_credit_override_requested({"credit_override": "true"})
        assert not is_credit_override_requested({"credit_override": False})
        assert not is_credit_override_requested({})

    def test_record_transaction_sets_and_clears_outstanding_since(self):
        owner, profile = _make_retailer("oe143_ledger", "OE143 Ledger")
        customer = _make_customer("oe143_ledger_cust", phone="9000000001")
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            current_balance=Decimal("0.00"),
        )
        assert mapping.outstanding_since is None

        mapping.record_transaction("SALE", Decimal("40.00"))
        mapping.refresh_from_db()
        assert mapping.current_balance == Decimal("40.00")
        assert mapping.outstanding_since is not None
        opened = mapping.outstanding_since

        mapping.record_transaction("SALE", Decimal("10.00"))
        mapping.refresh_from_db()
        assert mapping.outstanding_since == opened

        mapping.record_transaction("PAYMENT", Decimal("50.00"))
        mapping.refresh_from_db()
        assert mapping.current_balance == Decimal("0.00")
        assert mapping.outstanding_since is None


@pytest.mark.django_db
class TestPosCreditLock:
    def test_order_exceeding_credit_limit_is_blocked(self, api_client):
        owner, profile = _make_retailer("oe143_lim_owner", "OE143 Limit Shop")
        customer = _make_customer("oe143_lim_cust", phone="9000000011")
        product = _product(profile, price=Decimal("100.00"))
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("100.00"),
            current_balance=Decimal("50.00"),
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("create_pos_order"),
            _pos_credit_payload(product, customer.phone_number, Decimal("100.00")),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Credit limit exceeded" in resp.data["error"]
        mapping.refresh_from_db()
        assert mapping.current_balance == Decimal("50.00")
        assert not Order.objects.filter(retailer=profile, source="pos").exists()

    def test_overdue_outstanding_locks_new_credit_sales(self, api_client):
        owner, profile = _make_retailer("oe143_due_owner", "OE143 Due Shop")
        customer = _make_customer("oe143_due_cust", phone="9000000012")
        product = _product(profile, price=Decimal("50.00"))
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("0.00"),
            current_balance=Decimal("80.00"),
            credit_due_days=7,
            outstanding_since=timezone.now() - timedelta(days=10),
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("create_pos_order"),
            _pos_credit_payload(product, customer.phone_number, Decimal("50.00")),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "past due days" in resp.data["error"]
        mapping.refresh_from_db()
        assert mapping.current_balance == Decimal("80.00")
        assert not Order.objects.filter(retailer=profile, source="pos").exists()

    def test_owner_override_creates_order_and_audit(self, api_client):
        owner, profile = _make_retailer("oe143_ov_owner", "OE143 Override Shop")
        customer = _make_customer("oe143_ov_cust", phone="9000000013")
        product = _product(profile, price=Decimal("50.00"))
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("40.00"),
            current_balance=Decimal("20.00"),
            credit_due_days=5,
            outstanding_since=timezone.now() - timedelta(days=9),
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("create_pos_order"),
            _pos_credit_payload(
                product, customer.phone_number, Decimal("50.00"), override=True
            ),
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        mapping.refresh_from_db()
        assert mapping.current_balance == Decimal("70.00")
        order = Order.objects.get(retailer=profile, source="pos")
        row = OrgAuditLog.objects.get(
            organization=profile.organization,
            object_type=OrgAuditLog.OBJECT_CREDIT_OVERRIDE,
            object_id=str(order.id),
        )
        assert row.action == OrgAuditLog.ACTION_GRANT
        assert row.actor_id == owner.id
        assert REASON_CREDIT_LIMIT in row.summary_before["reasons"]
        assert REASON_CREDIT_OVERDUE in row.summary_before["reasons"]
        assert row.summary_after["override"] is True

    def test_override_without_orders_update_is_403(self, api_client):
        owner, profile = _make_retailer("oe143_staff_owner", "OE143 Staff Shop")
        customer = _make_customer("oe143_staff_cust", phone="9000000014")
        product = _product(profile, price=Decimal("50.00"))
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("10.00"),
            current_balance=Decimal("10.00"),
        )
        staff = _make_staff(
            profile.organization,
            "oe143_cashier",
            ["orders.create", "orders.read"],
        )
        assert PERM_CREDIT_OVERRIDE not in ["orders.create", "orders.read"]
        api_client.force_authenticate(user=staff)
        resp = api_client.post(
            reverse("create_pos_order"),
            {
                **_pos_credit_payload(
                    product, customer.phone_number, Decimal("50.00"), override=True
                ),
                "location_id": profile.id,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        mapping.refresh_from_db()
        assert mapping.current_balance == Decimal("10.00")
        assert not Order.objects.filter(retailer=profile, source="pos").exists()
        assert not OrgAuditLog.objects.filter(
            object_type=OrgAuditLog.OBJECT_CREDIT_OVERRIDE
        ).exists()

    def test_pay_while_locked_is_allowed(self, api_client):
        owner, profile = _make_retailer("oe143_pay_owner", "OE143 Pay Shop")
        customer = _make_customer("oe143_pay_cust", phone="9000000015")
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("10.00"),
            current_balance=Decimal("80.00"),
            credit_due_days=7,
            outstanding_since=timezone.now() - timedelta(days=20),
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("record_customer_payment"),
            {
                "customer_id": customer.id,
                "amount": "30.00",
                "payment_mode": "cash",
                "notes": "settle while locked",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        mapping.refresh_from_db()
        assert mapping.current_balance == Decimal("50.00")
        assert CustomerLedger.objects.filter(
            mapping=mapping, transaction_type="PAYMENT"
        ).exists()

    def test_cash_sale_not_blocked_when_overdue(self, api_client):
        owner, profile = _make_retailer("oe143_cash_owner", "OE143 Cash Shop")
        customer = _make_customer("oe143_cash_cust", phone="9000000016")
        product = _product(profile, price=Decimal("50.00"))
        RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            current_balance=Decimal("80.00"),
            credit_due_days=7,
            outstanding_since=timezone.now() - timedelta(days=20),
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            reverse("create_pos_order"),
            {
                "items": [
                    {
                        "product_id": product.id,
                        "quantity": 1,
                        "unit_price": "50.00",
                    }
                ],
                "subtotal": 50,
                "total_amount": 50,
                "customer_mobile": customer.phone_number,
                "payment_details": {"cash": 50},
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    def test_credit_finalize_query_budget(self, api_client, django_assert_num_queries):
        owner, profile = _make_retailer("oe143_q_owner", "OE143 Query Shop")
        customer = _make_customer("oe143_q_cust", phone="9000000017")
        product = _product(profile, price=Decimal("50.00"))
        RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("500.00"),
            current_balance=Decimal("10.00"),
            credit_due_days=30,
            outstanding_since=timezone.now() - timedelta(days=2),
        )
        api_client.force_authenticate(user=owner)
        with django_assert_num_queries(52):
            resp = api_client.post(
                reverse("create_pos_order"),
                _pos_credit_payload(product, customer.phone_number, Decimal("50.00")),
                format="json",
            )
        assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestCreditSettingsAuthAndTenancy:
    def test_customer_cannot_mutate_limit_or_due_days(self, api_client):
        owner, profile = _make_retailer("oe143_403_owner", "OE143 403 Shop")
        customer = _make_customer("oe143_403_cust", phone="9000000021")
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("100.00"),
            credit_due_days=14,
        )
        api_client.force_authenticate(user=customer)
        resp = api_client.patch(
            reverse("update_customer_credit_limit", args=[customer.id]),
            {"credit_limit": "999.00", "credit_due_days": 1},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        mapping.refresh_from_db()
        assert mapping.credit_limit == Decimal("100.00")
        assert mapping.credit_due_days == 14

    def test_cross_tenant_cannot_mutate_other_shop_mapping(self, api_client):
        owner_a, profile_a = _make_retailer("oe143_a_owner", "OE143 Shop A")
        owner_b, profile_b = _make_retailer("oe143_b_owner", "OE143 Shop B")
        customer = _make_customer("oe143_shared_cust", phone="9000000022")
        mapping_a = RetailerCustomerMapping.objects.create(
            retailer=profile_a,
            customer=customer,
            credit_limit=Decimal("100.00"),
            credit_due_days=14,
            current_balance=Decimal("25.00"),
        )
        api_client.force_authenticate(user=owner_b)
        resp = api_client.patch(
            reverse("update_customer_credit_limit", args=[customer.id]),
            {"credit_limit": "1.00", "credit_due_days": 1},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        mapping_a.refresh_from_db()
        assert mapping_a.credit_limit == Decimal("100.00")
        assert mapping_a.credit_due_days == 14
        assert mapping_a.current_balance == Decimal("25.00")

    def test_owner_can_set_due_days(self, api_client):
        owner, profile = _make_retailer("oe143_set_owner", "OE143 Set Shop")
        customer = _make_customer("oe143_set_cust", phone="9000000023")
        mapping = RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            credit_limit=Decimal("100.00"),
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            reverse("update_customer_credit_limit", args=[customer.id]),
            {"credit_due_days": 15},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        mapping.refresh_from_db()
        assert mapping.credit_due_days == 15
        assert mapping.credit_limit == Decimal("100.00")

    def test_cashier_role_has_no_credit_override_perm(self):
        owner, profile = _make_retailer("oe143_cashrole", "OE143 Cashier Role")
        cashier = OrgRole.objects.get(
            organization=profile.organization, slug=ROLE_SLUG_CASHIER
        )
        assert PERM_CREDIT_OVERRIDE not in (cashier.permissions or [])
