import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from authentication.models import User
from customers.models import CustomerProfile
from retailers.models import RetailerCustomerMapping, RetailerProfile


def _make_retailer(username, shop_name):
    owner = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    return RetailerProfile.objects.create(
        user=owner,
        shop_name=shop_name,
        address_line1="1 Shop St",
        city="TestCity",
        state="TestState",
        pincode="123456",
        is_active=True,
    )


def _make_customer(username):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
        is_email_verified=True,
    )
    CustomerProfile.objects.create(user=user)
    return user


@pytest.mark.django_db
class TestGetAllCustomerCreditKAN70:
    def test_unauthenticated_is_rejected(self, api_client):
        url = reverse("get_all_customer_credit")
        response = api_client.get(url)
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_retailer_user_is_forbidden(self, api_client, retailer_user):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("get_all_customer_credit")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_empty_when_customer_has_no_mappings(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        url = reverse("get_all_customer_credit")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_includes_zero_credit_limit_and_zero_balance(self, api_client, customer, retailer):
        RetailerCustomerMapping.objects.create(
            retailer=retailer,
            customer=customer,
            credit_limit=Decimal("0.00"),
            current_balance=Decimal("0.00"),
        )
        api_client.force_authenticate(user=customer)
        url = reverse("get_all_customer_credit")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        row = response.data[0]
        assert row["retailer_id"] == retailer.id
        assert row["retailer_name"] == retailer.shop_name
        assert float(row["credit_limit"]) == 0.0
        assert float(row["current_balance"]) == 0.0
        assert float(row["remaining_credit"]) == 0.0

    def test_includes_outstanding_when_credit_limit_is_zero(self, api_client, customer, retailer):
        RetailerCustomerMapping.objects.create(
            retailer=retailer,
            customer=customer,
            credit_limit=Decimal("0.00"),
            current_balance=Decimal("75.50"),
        )
        api_client.force_authenticate(user=customer)
        url = reverse("get_all_customer_credit")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        row = response.data[0]
        assert float(row["credit_limit"]) == 0.0
        assert float(row["current_balance"]) == 75.5
        assert float(row["remaining_credit"]) == -75.5

    def test_returns_retailer_wise_balances(self, api_client, customer, retailer):
        other = _make_retailer("kan70_other_owner", "Second Shop")
        RetailerCustomerMapping.objects.create(
            retailer=retailer,
            customer=customer,
            credit_limit=Decimal("500.00"),
            current_balance=Decimal("200.00"),
        )
        RetailerCustomerMapping.objects.create(
            retailer=other,
            customer=customer,
            credit_limit=Decimal("0.00"),
            current_balance=Decimal("10.00"),
        )
        api_client.force_authenticate(user=customer)
        url = reverse("get_all_customer_credit")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        by_id = {row["retailer_id"]: row for row in response.data}
        assert set(by_id) == {retailer.id, other.id}
        assert float(by_id[retailer.id]["remaining_credit"]) == 300.0
        assert float(by_id[other.id]["current_balance"]) == 10.0
        assert float(by_id[other.id]["credit_limit"]) == 0.0

    def test_does_not_leak_other_customer_mappings(self, api_client, customer, retailer):
        stranger = _make_customer("kan70_stranger")
        RetailerCustomerMapping.objects.create(
            retailer=retailer,
            customer=stranger,
            credit_limit=Decimal("999.00"),
            current_balance=Decimal("111.00"),
        )
        api_client.force_authenticate(user=customer)
        url = reverse("get_all_customer_credit")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
