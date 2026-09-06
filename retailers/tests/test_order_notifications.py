"""
OE-183 / F-0005 — Order status notification dispatcher and org APIs.

Covers AC: status-change emit, disable non-statutory type, retry + last-error,
bulk blast permission gate, cross-tenant isolation, audit on config change.
"""
import pytest
from unittest.mock import patch
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from common.notification_catalog import (
    NOTIFICATION_CATALOG_VERSION,
    NON_STATUTORY_NOTIFICATION_TYPES,
    STATUTORY_NOTIFICATION_TYPES,
)
from common.notification_dispatcher import (
    dispatch_notification,
    retry_notification_delivery,
)
from customers.models import CustomerNotification
from retailers.models import (
    OrgAuditLog,
    OrgNotificationConfig,
    OrgNotificationDelivery,
    OrgRole,
    OrgStaffMembership,
    RetailerCustomerMapping,
    RetailerProfile,
)
from retailers.organization import ensure_organization_for_profile
from retailers.permissions_catalog import PERMISSION_CATALOG_VERSION
from orders.models import Order, OrderItem
from decimal import Decimal
from customers.models import CustomerProfile, CustomerAddress


def _make_retailer(username, shop_name, *, with_org=True):
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
    if with_org:
        ensure_organization_for_profile(profile, name=f"{shop_name} Org")
    return user, profile


def _make_customer(username):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
    )
    return user


def _catalog_url(org_id):
    return reverse("organization_notification_catalog", kwargs={"org_id": org_id})


def _config_url(org_id):
    return reverse("organization_notification_config", kwargs={"org_id": org_id})


def _deliveries_url(org_id):
    return reverse("organization_notification_deliveries", kwargs={"org_id": org_id})


def _retry_url(org_id, delivery_id):
    return reverse(
        "organization_notification_delivery_retry",
        kwargs={"org_id": org_id, "delivery_id": delivery_id},
    )


def _blast_url(org_id):
    return reverse("organization_notification_blast", kwargs={"org_id": org_id})


@pytest.fixture
def notification_order(customer, retailer, product):
    address = CustomerAddress.objects.create(
        customer=customer,
        address_line1="1 Test Lane",
        city="City",
        state="State",
        pincode="110001",
        is_default=True,
    )
    CustomerProfile.objects.get_or_create(user=customer)
    order = Order.objects.create(
        customer=customer,
        retailer=retailer,
        delivery_address=address,
        delivery_mode="delivery",
        payment_mode="cash",
        subtotal=Decimal("200.00"),
        total_amount=Decimal("200.00"),
        status="pending",
    )
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        product_price=product.price,
        product_unit=product.unit,
        quantity=2,
        unit_price=product.price,
        total_price=Decimal("200.00"),
    )
    return order


@pytest.mark.django_db
class TestNotificationCatalogAndPermissions:
    def test_catalog_endpoint_versioned(self, api_client):
        owner, profile = _make_retailer("notif_cat_owner", "Notif Cat Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.get(_catalog_url(org.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == NOTIFICATION_CATALOG_VERSION
        codes = {t["code"] for t in resp.data["notification_types"]}
        assert "order.status.confirmed" in codes

    def test_notification_permissions_in_catalog(self, api_client):
        owner, profile = _make_retailer("notif_perm_owner", "Notif Perm Shop")
        org = profile.organization
        api_client.force_authenticate(user=owner)
        resp = api_client.get(
            reverse("organization_permission_catalog", kwargs={"org_id": org.id})
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["version"] == PERMISSION_CATALOG_VERSION
        codes = {p["code"] for p in resp.data["permissions"]}
        assert "notifications.manage" in codes
        assert "notifications.blast" in codes


@pytest.mark.django_db
class TestOrderStatusDispatch:
    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    @patch("common.notifications.send_silent_update")
    def test_status_change_emits_delivery(self, mock_silent, mock_deliver, notification_order):
        notification_order.update_status("confirmed", user=None)
        delivery = OrgNotificationDelivery.objects.filter(
            order=notification_order,
            notification_type="order.status.confirmed",
        ).first()
        assert delivery is not None
        assert delivery.status == OrgNotificationDelivery.STATUS_SENT
        assert delivery.organization_id == notification_order.retailer.organization_id

    @patch("common.notifications.send_push_notification", return_value=True)
    @patch("common.notifications.send_silent_update")
    def test_status_change_creates_customer_inbox(self, mock_silent, mock_push, notification_order):
        notification_order.update_status("confirmed", user=None)
        assert CustomerNotification.objects.filter(
            customer=notification_order.customer,
            notification_type="order_update",
        ).exists()

    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    @patch("common.notifications.send_silent_update")
    def test_disabled_non_statutory_type_skips_emit(self, mock_silent, mock_deliver, notification_order):
        org = notification_order.retailer.organization
        config = OrgNotificationConfig.objects.get(organization=org)
        config.disabled_types = ["order.status.confirmed"]
        config.save(update_fields=["disabled_types"])

        notification_order.update_status("confirmed", user=None)
        assert not OrgNotificationDelivery.objects.filter(
            order=notification_order,
            notification_type="order.status.confirmed",
        ).exists()
        mock_deliver.assert_not_called()

    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    @patch("common.notifications.send_silent_update")
    def test_statutory_type_cannot_be_disabled(self, mock_silent, mock_deliver, notification_order):
        org = notification_order.retailer.organization
        config = OrgNotificationConfig.objects.get(organization=org)
        config.disabled_types = ["order.status.delivered"]
        config.save(update_fields=["disabled_types"])

        notification_order.update_status("delivered", user=None)
        assert OrgNotificationDelivery.objects.filter(
            order=notification_order,
            notification_type="order.status.delivered",
        ).exists()


@pytest.mark.django_db
class TestNotificationRetryAndErrors:
    @patch(
        "common.notification_dispatcher._deliver_via_channel",
        side_effect=[(False, "channel timeout"), (True, None)],
    )
    def test_failed_send_records_last_error_and_retry_succeeds(self, mock_deliver, notification_order, retailer):
        delivery, _skip = dispatch_notification(
            organization=retailer.organization,
            notification_type="order.status.processing",
            recipient_user=notification_order.customer,
            order=notification_order,
            location=retailer,
        )
        assert delivery.status == OrgNotificationDelivery.STATUS_FAILED
        assert delivery.last_error == "channel timeout"

        delivery, err = retry_notification_delivery(delivery)
        assert err is None
        assert delivery.status == OrgNotificationDelivery.STATUS_SENT
        assert delivery.last_error == ""


@pytest.mark.django_db
class TestNotificationConfigAPI:
    def test_owner_can_patch_disable_non_statutory(self, api_client):
        owner, profile = _make_retailer("notif_cfg_owner", "Notif Cfg Shop")
        org = profile.organization
        disabled = sorted(NON_STATUTORY_NOTIFICATION_TYPES)[:1]
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            _config_url(org.id),
            {"disabled_types": disabled},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["disabled_types"] == disabled
        assert OrgAuditLog.objects.filter(
            organization=org,
            object_type=OrgAuditLog.OBJECT_NOTIFICATION_CONFIG,
        ).exists()

    def test_cannot_disable_statutory_type_via_api(self, api_client):
        owner, profile = _make_retailer("notif_stat_owner", "Notif Stat Shop")
        org = profile.organization
        statutory = sorted(STATUTORY_NOTIFICATION_TYPES)[0]
        api_client.force_authenticate(user=owner)
        resp = api_client.patch(
            _config_url(org.id),
            {"disabled_types": [statutory]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cashier_cannot_patch_config(self, api_client):
        owner, profile = _make_retailer("notif_cash_owner", "Notif Cash Shop")
        org = profile.organization
        cashier_role = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=owner)
        cashier = User.objects.create_user(
            username="notif_cashier",
            email="notif_cashier@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        OrgStaffMembership.objects.create(
            organization=org,
            user=cashier,
            role=cashier_role,
            is_active=True,
        )
        api_client.force_authenticate(user=cashier)
        resp = api_client.patch(
            _config_url(org.id),
            {"disabled_types": ["order.status.processing"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestNotificationBlastPermission:
    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    def test_blast_blocked_without_permission(self, mock_deliver, api_client):
        owner, profile = _make_retailer("notif_blast_owner", "Notif Blast Shop")
        org = profile.organization
        customer = _make_customer("notif_blast_customer")
        cashier_role = OrgRole.objects.get(organization=org, slug="cashier")
        api_client.force_authenticate(user=owner)
        cashier = User.objects.create_user(
            username="notif_blast_cashier",
            email="notif_blast_cashier@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        OrgStaffMembership.objects.create(
            organization=org,
            user=cashier,
            role=cashier_role,
            is_active=True,
        )
        api_client.force_authenticate(user=cashier)
        resp = api_client.post(
            _blast_url(org.id),
            {
                "notification_type": "order.status.processing",
                "recipient_user_ids": [customer.id],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    def test_owner_can_blast(self, mock_deliver, api_client):
        owner, profile = _make_retailer("notif_blast_ok", "Notif Blast OK")
        org = profile.organization
        customer = _make_customer("notif_blast_ok_customer")
        RetailerCustomerMapping.objects.create(
            retailer=profile,
            customer=customer,
            customer_type="online",
        )
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            _blast_url(org.id),
            {
                "notification_type": "order.status.processing",
                "recipient_user_ids": [customer.id],
                "context": {"order_number": "ORD-TEST-1"},
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["deliveries"]) == 1

    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    def test_blast_excludes_customers_not_mapped_to_org(self, mock_deliver, api_client):
        owner, profile = _make_retailer("notif_blast_nomap", "Notif Blast NoMap")
        org = profile.organization
        unmapped = _make_customer("notif_blast_unmapped")
        api_client.force_authenticate(user=owner)
        resp = api_client.post(
            _blast_url(org.id),
            {
                "notification_type": "order.status.processing",
                "recipient_user_ids": [unmapped.id],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        mock_deliver.assert_not_called()

    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    def test_blast_for_org_a_does_not_include_org_b_customers(self, mock_deliver, api_client):
        owner_a, profile_a = _make_retailer("notif_blast_a", "Notif Blast A")
        owner_b, profile_b = _make_retailer("notif_blast_b", "Notif Blast B")
        customer_b = _make_customer("notif_blast_only_b")
        RetailerCustomerMapping.objects.create(
            retailer=profile_b,
            customer=customer_b,
            customer_type="online",
        )
        api_client.force_authenticate(user=owner_a)
        resp = api_client.post(
            _blast_url(profile_a.organization.id),
            {
                "notification_type": "order.status.processing",
                "recipient_user_ids": [customer_b.id],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert not OrgNotificationDelivery.objects.filter(
            organization=profile_a.organization,
            recipient_user=customer_b,
        ).exists()
        mock_deliver.assert_not_called()

    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    def test_blast_mixed_ids_only_delivers_to_org_mapped(self, mock_deliver, api_client):
        owner_a, profile_a = _make_retailer("notif_blast_mix_a", "Notif Blast Mix A")
        owner_b, profile_b = _make_retailer("notif_blast_mix_b", "Notif Blast Mix B")
        customer_a = _make_customer("notif_blast_mix_a_cust")
        customer_b = _make_customer("notif_blast_mix_b_cust")
        RetailerCustomerMapping.objects.create(
            retailer=profile_a,
            customer=customer_a,
            customer_type="online",
        )
        RetailerCustomerMapping.objects.create(
            retailer=profile_b,
            customer=customer_b,
            customer_type="online",
        )
        api_client.force_authenticate(user=owner_a)
        resp = api_client.post(
            _blast_url(profile_a.organization.id),
            {
                "notification_type": "order.status.processing",
                "recipient_user_ids": [customer_a.id, customer_b.id],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data["deliveries"]) == 1
        assert resp.data["deliveries"][0]["recipient_user_id"] == customer_a.id


@pytest.mark.django_db
class TestNotificationCrossTenant:
    def test_cross_tenant_config_read_forbidden(self, api_client):
        owner_a, profile_a = _make_retailer("notif_tenant_a", "Notif Tenant A")
        owner_b, profile_b = _make_retailer("notif_tenant_b", "Notif Tenant B")
        api_client.force_authenticate(user=owner_a)
        resp = api_client.get(_config_url(profile_b.organization.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_delivery_list_forbidden(self, api_client):
        owner_a, profile_a = _make_retailer("notif_tenant_a2", "Notif Tenant A2")
        owner_b, profile_b = _make_retailer("notif_tenant_b2", "Notif Tenant B2")
        api_client.force_authenticate(user=owner_a)
        resp = api_client.get(_deliveries_url(profile_b.organization.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    @patch("common.notification_dispatcher._deliver_via_channel", return_value=(True, None))
    def test_cross_tenant_retry_forbidden(self, mock_deliver, api_client):
        owner_a, profile_a = _make_retailer("notif_tenant_a3", "Notif Tenant A3")
        owner_b, profile_b = _make_retailer("notif_tenant_b3", "Notif Tenant B3")
        delivery, _ = dispatch_notification(
            organization=profile_b.organization,
            notification_type="order.status.processing",
            recipient_user=_make_customer("notif_cross_cust"),
        )
        api_client.force_authenticate(user=owner_a)
        resp = api_client.post(_retry_url(profile_b.organization.id, delivery.id))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_config_returns_401(self, api_client):
        owner, profile = _make_retailer("notif_unauth", "Notif Unauth")
        resp = api_client.get(_config_url(profile.organization.id))
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
