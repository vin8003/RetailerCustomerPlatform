"""
Customer signup replaces only a leftover signup attempt: an account that verified a phone
or an email, or that has orders, is kept.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from orders.models import Order

PHONE = '+919876500011'


def _customer(username, **flags):
    user = User.objects.create_user(
        username=username,
        password='OldPass@123',
        user_type='customer',
        phone_number=PHONE,
        email=f'{username}@example.com',
    )
    for field, value in flags.items():
        setattr(user, field, value)
    user.save()
    return user


def _order(customer, shop):
    return Order.objects.create(
        customer=customer,
        retailer=shop,
        source='app',
        status='delivered',
        subtotal=Decimal('90.00'),
        total_amount=Decimal('90.00'),
        payment_mode='cash',
        delivery_mode='pickup',
    )


@pytest.mark.django_db
class TestSignupKeepsRealCustomers:
    def test_phone_verified_customer_and_orders_are_kept(
        self, api_client, retailer, mock_email_send
    ):
        customer = _customer('otp_customer', is_phone_verified=True)
        order = _order(customer, retailer)

        response = api_client.post(reverse('customer_signup'), {'phone_number': PHONE}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert User.objects.filter(pk=customer.pk).exists()
        assert Order.objects.filter(pk=order.pk).exists()

    def test_customer_with_orders_is_kept(
        self, api_client, retailer, mock_email_send
    ):
        customer = _customer('ordered_customer')
        order = _order(customer, retailer)

        response = api_client.post(
            reverse('customer_signup'),
            {
                'username': 'ordered_customer',
                'password': 'NewPass@123',
                'password_confirm': 'NewPass@123',
                'email': 'someone.else@example.com',
                'phone_number': '+919876500099',
            },
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert User.objects.get(pk=customer.pk).check_password('OldPass@123')
        assert Order.objects.filter(pk=order.pk).exists()

    def test_email_verified_customer_is_kept(self, api_client, mock_email_send):
        customer = _customer('email_customer', is_email_verified=True)

        api_client.post(reverse('customer_signup'), {'email': 'email_customer@example.com'}, format='json')

        assert User.objects.filter(pk=customer.pk).exists()

    def test_never_verified_attempt_without_orders_is_still_replaced(self, api_client, mock_email_send):
        stale = _customer('retry_customer')

        response = api_client.post(
            reverse('customer_signup'),
            {
                'username': 'retry_customer',
                'password': 'NewPass@123',
                'password_confirm': 'NewPass@123',
                'email': 'retry_customer@example.com',
                'phone_number': PHONE,
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert not User.objects.filter(pk=stale.pk).exists()
        assert User.objects.get(username='retry_customer').check_password('NewPass@123')

    def test_non_text_identifiers_are_a_400_not_a_500(self, api_client, mock_email_send):
        response = api_client.post(
            reverse('customer_signup'),
            {'username': 123, 'phone_number': 9876500011, 'email': 5, 'password': 'x', 'password_confirm': 'x'},
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
