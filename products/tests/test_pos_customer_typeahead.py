import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from authentication.models import User
from customers.models import CustomerProfile
from orders.models import Order
from retailers.models import RetailerCustomerMapping, RetailerProfile


def _make_customer(username, phone, first_name='', registration_status='registered'):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        phone_number=phone,
        first_name=first_name,
        registration_status=registration_status,
        is_active=True,
    )
    CustomerProfile.objects.create(user=user)
    return user


def _make_order(retailer, customer):
    return Order.objects.create(
        customer=customer,
        retailer=retailer,
        source='app',
        delivery_mode='pickup',
        payment_mode='upi',
        subtotal=Decimal('100.00'),
        total_amount=Decimal('100.00'),
    )


@pytest.mark.django_db
class TestSearchPosCustomersKAN73:
    def test_excludes_other_retailer_customers(self, api_client, retailer_user, retailer):
        other_user = User.objects.create_user(
            username="other_shop_owner",
            email="other_shop@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        other_retailer = RetailerProfile.objects.create(
            user=other_user,
            shop_name="Other Shop",
            address_line1="1 Other St",
            city="OtherCity",
            state="OtherState",
            pincode="999999",
            is_active=True,
        )
        stranger = _make_customer("9876500000", "9876500000", first_name="Stranger")
        RetailerCustomerMapping.objects.create(retailer=other_retailer, customer=stranger)

        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("search_pos_customers"), {"q": "987"})
        assert res.status_code == status.HTTP_200_OK
        mobiles = [s["mobile"] for s in res.data]
        assert "9876500000" not in mobiles

    def test_includes_mapped_walk_in(self, api_client, retailer_user, retailer):
        walkin = _make_customer(
            "9001112233", "9001112233", first_name="Ramesh", registration_status="shadow"
        )
        RetailerCustomerMapping.objects.create(
            retailer=retailer, customer=walkin, nickname="Ramesh", customer_type="walk_in"
        )

        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("search_pos_customers"), {"q": "900"})
        assert res.status_code == status.HTTP_200_OK
        hit = next(s for s in res.data if s["mobile"] == "9001112233")
        assert hit["name"] == "Ramesh"

    def test_includes_online_shopper_without_mapping(self, api_client, retailer_user, retailer):
        online = _make_customer("9123456789", "9123456789", first_name="Priya")
        _make_order(retailer, online)
        assert not RetailerCustomerMapping.objects.filter(
            retailer=retailer, customer=online
        ).exists()

        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("search_pos_customers"), {"q": "912"})
        assert res.status_code == status.HTTP_200_OK
        hit = next((s for s in res.data if s["mobile"] == "9123456789"), None)
        assert hit is not None, "Online shopper who ordered from this retailer must appear in POS typeahead"
        assert "Priya" in hit["name"]

    def test_other_retailer_online_order_not_visible(self, api_client, retailer_user, retailer):
        other_user = User.objects.create_user(
            username="shop2_owner",
            email="shop2@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        other_retailer = RetailerProfile.objects.create(
            user=other_user,
            shop_name="Shop Two",
            address_line1="2 Other St",
            city="OtherCity",
            state="OtherState",
            pincode="888888",
            is_active=True,
        )
        online = _make_customer("9111222333", "9111222333", first_name="Meera")
        _make_order(other_retailer, online)

        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("search_pos_customers"), {"q": "911"})
        assert res.status_code == status.HTTP_200_OK
        mobiles = [s["mobile"] for s in res.data]
        assert "9111222333" not in mobiles
