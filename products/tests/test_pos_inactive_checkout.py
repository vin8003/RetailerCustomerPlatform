import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from products.models import Product
from orders.models import Order
from authentication.models import User
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile


def _pos_payload(product, quantity=1):
    unit = float(product.price)
    line_total = unit * quantity
    return {
        "payment_mode": "cash",
        "subtotal": line_total,
        "total_amount": line_total,
        "items": [
            {
                "product_id": product.id,
                "quantity": quantity,
                "unit_price": unit,
            }
        ],
    }


@pytest.mark.django_db
class TestPOSSaleableCheckout:
    """
    OE-190 AC2 (POS): create_pos_order must reject inactive or unavailable
    products. Customer cart already enforces is_active+is_available.
    """

    def test_inactive_product_cannot_pos_checkout(
        self, api_client, retailer_user, product
    ):
        product.is_active = False
        product.save(update_fields=["is_active"])
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.data.get("error", "")
        assert str(product.id) in error
        assert product.name in error
        assert not Order.objects.filter(source="pos").exists()

    def test_unavailable_product_cannot_pos_checkout(
        self, api_client, retailer_user, product
    ):
        product.is_available = False
        product.save(update_fields=["is_available"])
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.data.get("error", "")
        assert str(product.id) in error
        assert product.name in error
        assert not Order.objects.filter(source="pos").exists()

    def test_active_available_product_pos_checkout_succeeds(
        self, api_client, retailer_user, product
    ):
        api_client.force_authenticate(user=retailer_user)

        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(product),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Order.objects.filter(source="pos", retailer=product.retailer).exists()

    def test_active_available_pos_checkout_query_count(
        self, api_client, retailer_user, product, django_assert_num_queries
    ):
        api_client.force_authenticate(user=retailer_user)
        with django_assert_num_queries(28):
            response = api_client.post(
                reverse("create_pos_order"),
                _pos_payload(product),
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED

    def test_mixed_cart_inactive_rejects_entire_order(
        self, api_client, retailer_user, product, product2
    ):
        product2.is_active = False
        product2.save(update_fields=["is_active"])
        api_client.force_authenticate(user=retailer_user)

        payload = {
            "payment_mode": "cash",
            "subtotal": float(product.price + product2.price),
            "total_amount": float(product.price + product2.price),
            "items": [
                {
                    "product_id": product.id,
                    "quantity": 1,
                    "unit_price": float(product.price),
                },
                {
                    "product_id": product2.id,
                    "quantity": 1,
                    "unit_price": float(product2.price),
                },
            ],
        }

        response = api_client.post(
            reverse("create_pos_order"), payload, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Order.objects.filter(source="pos").exists()

    def test_cross_tenant_product_cannot_pos_checkout(
        self, api_client, retailer_user, retailer, category, brand
    ):
        other_user = User.objects.create_user(
            username="oe190_other_retailer",
            email="oe190_other@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        other_retailer = RetailerProfile.objects.create(
            user=other_user,
            shop_name="OE190 Other Shop",
            address_line1="9 Side St",
            city="OtherCity",
            state="OtherState",
            pincode="654321",
            is_active=True,
        )
        ensure_organization_for_profile(other_retailer)
        foreign = Product.objects.create(
            retailer=other_retailer,
            name="Foreign Tea",
            category=category,
            brand=brand,
            price=Decimal("40.00"),
            quantity=10,
            track_inventory=True,
            is_active=True,
            is_available=True,
        )

        api_client.force_authenticate(user=retailer_user)
        response = api_client.post(
            reverse("create_pos_order"),
            _pos_payload(foreign),
            format="json",
        )

        assert response.status_code != status.HTTP_201_CREATED
        assert not Order.objects.filter(retailer=retailer, source="pos").exists()
        assert not Order.objects.filter(retailer=other_retailer, source="pos").exists()
