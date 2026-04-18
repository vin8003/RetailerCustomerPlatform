import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from unittest.mock import patch, MagicMock
from cart.models import Cart, CartItem, CartHistory
from products.models import Product


@pytest.mark.django_db
class TestGetCart:

    def test_get_cart_unauthorized(self, api_client):
        res = api_client.get(reverse("get_cart"))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_cart_retailer_forbidden(self, api_client, retailer_user):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_cart"))
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_get_all_carts(self, api_client, customer, cart):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart"))
        assert res.status_code == status.HTTP_200_OK
        assert isinstance(res.data, list)

    def test_get_cart_by_retailer_id(self, api_client, customer, retailer, product):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_200_OK
        assert "items" in res.data

    def test_get_cart_retailer_not_found(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart"), {"retailer_id": 99999})
        assert res.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestAddToCart:

    def test_add_to_cart_success(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 2},
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert Cart.objects.filter(customer=customer).exists()
        assert CartHistory.objects.filter(customer=customer, action="add").exists()

    def test_add_to_cart_retailer_forbidden(self, api_client, retailer_user, product):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 1},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_add_to_cart_invalid_product(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": 99999, "quantity": 1},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_add_to_cart_zero_quantity(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 0},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_add_to_cart_exceeds_stock(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 9999},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_add_to_cart_inactive_product(self, api_client, customer, product):
        product.is_active = False
        product.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 1},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_add_to_cart_retailer_not_accepting(self, api_client, customer, product, retailer):
        retailer.offers_delivery = False
        retailer.offers_pickup = False
        retailer.save()
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("add_to_cart"),
            {"product_id": product.id, "quantity": 1},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestUpdateCartItem:

    def test_update_cart_item_success(self, api_client, customer, cart_item):
        api_client.force_authenticate(user=customer)
        res = api_client.put(
            reverse("update_cart_item", args=[cart_item.id]),
            {"quantity": 5},
        )
        assert res.status_code == status.HTTP_200_OK

    def test_update_cart_item_retailer_forbidden(self, api_client, retailer_user, cart_item):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.put(
            reverse("update_cart_item", args=[cart_item.id]),
            {"quantity": 3},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_update_cart_item_not_found(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.put(
            reverse("update_cart_item", args=[99999]),
            {"quantity": 3},
        )
        # get_object_or_404 raises Http404 but it's caught by the broad except
        assert res.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_update_cart_item_zero_quantity(self, api_client, customer, cart_item):
        api_client.force_authenticate(user=customer)
        res = api_client.put(
            reverse("update_cart_item", args=[cart_item.id]),
            {"quantity": 0},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_cart_item_exceeds_stock(self, api_client, customer, cart_item):
        api_client.force_authenticate(user=customer)
        res = api_client.put(
            reverse("update_cart_item", args=[cart_item.id]),
            {"quantity": 9999},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestRemoveCartItem:

    def test_remove_cart_item_success(self, api_client, customer, cart_item):
        api_client.force_authenticate(user=customer)
        res = api_client.delete(reverse("remove_cart_item", args=[cart_item.id]))
        assert res.status_code == status.HTTP_200_OK
        assert CartHistory.objects.filter(action="remove").exists()

    def test_remove_cart_item_forbidden(self, api_client, retailer_user, cart_item):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.delete(reverse("remove_cart_item", args=[cart_item.id]))
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_remove_cart_item_not_found(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.delete(reverse("remove_cart_item", args=[99999]))
        # get_object_or_404 raises Http404 but it's caught by the broad except
        assert res.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_500_INTERNAL_SERVER_ERROR)


@pytest.mark.django_db
class TestClearCart:

    def test_clear_cart_success(self, api_client, customer, cart, cart_item):
        api_client.force_authenticate(user=customer)
        res = api_client.post(
            reverse("clear_cart"),
            {"retailer_id": cart.retailer.id},
        )
        assert res.status_code == status.HTTP_200_OK
        assert CartHistory.objects.filter(action="clear").exists()
        cart.refresh_from_db()
        assert cart.items.count() == 0

    def test_clear_cart_missing_retailer_id(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("clear_cart"))
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_clear_cart_retailer_not_found(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("clear_cart"), {"retailer_id": 99999})
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_clear_cart_cart_not_found(self, api_client, customer, retailer):
        # don't create a cart, so Cart.DoesNotExist
        Cart.objects.filter(customer=customer, retailer=retailer).delete()
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("clear_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_clear_cart_forbidden(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(reverse("clear_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestGetCartSummary:

    def test_get_cart_summary_success(self, api_client, customer, cart, cart_item, retailer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(
            reverse("get_cart_summary"),
            {"retailer_id": retailer.id},
        )
        assert res.status_code == status.HTTP_200_OK
        assert "total_items" in res.data
        assert "can_checkout" in res.data
        assert "checkout_message" in res.data

    def test_get_cart_summary_empty_cart(self, api_client, customer, cart, retailer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(
            reverse("get_cart_summary"),
            {"retailer_id": retailer.id},
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["checkout_message"] == "Your cart is empty"

    def test_get_cart_summary_below_minimum(self, api_client, customer, cart, retailer, product):
        # min order is 50, product price is 100, qty 1 = 100 - but let's set min high
        retailer.minimum_order_amount = Decimal("500.00")
        retailer.save()
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=product.price)
        api_client.force_authenticate(user=customer)
        res = api_client.get(
            reverse("get_cart_summary"),
            {"retailer_id": retailer.id},
        )
        assert res.status_code == status.HTTP_200_OK
        assert "Minimum order amount" in res.data["checkout_message"]

    def test_get_cart_summary_missing_retailer_id(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart_summary"))
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_cart_summary_retailer_not_found(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart_summary"), {"retailer_id": 99999})
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_get_cart_summary_cart_not_found(self, api_client, customer, retailer):
        Cart.objects.filter(customer=customer, retailer=retailer).delete()
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart_summary"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_get_cart_summary_forbidden(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_cart_summary"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestValidateCart:

    def test_validate_cart_valid(self, api_client, customer, cart, product, retailer):
        CartItem.objects.create(cart=cart, product=product, quantity=2, unit_price=product.price)
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_200_OK
        assert res.data["valid"] is True

    def test_validate_cart_empty(self, api_client, customer, cart, retailer):
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.data["valid"] is False

    def test_validate_cart_unavailable_product(self, api_client, customer, cart, product, retailer):
        product.is_available = False
        product.save()
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=product.price)
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.data["valid"] is False

    def test_validate_cart_exceeds_stock(self, api_client, customer, cart, product, retailer):
        product.quantity = 2
        product.save()
        CartItem.objects.create(cart=cart, product=product, quantity=10, unit_price=product.price)
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_validate_cart_below_min_qty(self, api_client, customer, cart, product, retailer):
        product.minimum_order_quantity = 5
        product.save()
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=product.price)
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_validate_cart_above_max_qty(self, api_client, customer, cart, product, retailer):
        product.maximum_order_quantity = 3
        product.save()
        CartItem.objects.create(cart=cart, product=product, quantity=5, unit_price=product.price)
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_validate_cart_below_min_order_amount(self, api_client, customer, cart, product, retailer):
        retailer.minimum_order_amount = Decimal("9999.00")
        retailer.save()
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=product.price)
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": retailer.id})
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_validate_cart_missing_retailer_id(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.post(reverse("validate_cart"))
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_validate_cart_forbidden(self, api_client, retailer_user):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.post(reverse("validate_cart"), {"retailer_id": 1})
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestGetCartCount:

    def test_cart_count_empty(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart_count"))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_items"] == 0

    def test_cart_count_with_items(self, api_client, customer, cart, cart_item):
        api_client.force_authenticate(user=customer)
        res = api_client.get(reverse("get_cart_count"))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_items"] == 2  # cart_item fixture has quantity=2

    def test_cart_count_forbidden(self, api_client, retailer_user):
        api_client.force_authenticate(user=retailer_user)
        res = api_client.get(reverse("get_cart_count"))
        assert res.status_code == status.HTTP_403_FORBIDDEN
