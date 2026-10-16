import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status

from orders.models import Order, OrderItem
from products.models import Product


@pytest.mark.django_db
class TestFrequentlyBoughtTogether:
    def test_empty_without_seeds(self, api_client, retailer):
        url = reverse('get_frequently_bought_together', kwargs={'retailer_id': retailer.id})
        res = api_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data == []

    def test_suggests_same_category_and_excludes_seed(
        self, api_client, retailer, category, brand, product
    ):
        companion = Product.objects.create(
            retailer=retailer,
            name="Bread",
            category=category,
            brand=brand,
            price=Decimal("40.00"),
            quantity=20,
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="piece",
        )
        other_cat_product = Product.objects.create(
            retailer=retailer,
            name="Soap",
            brand=brand,
            price=Decimal("15.00"),
            quantity=20,
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="piece",
        )
        url = reverse('get_frequently_bought_together', kwargs={'retailer_id': retailer.id})
        res = api_client.get(url, {'product_ids': str(product.id)})
        assert res.status_code == status.HTTP_200_OK
        ids = [row['id'] for row in res.data]
        assert companion.id in ids
        assert product.id not in ids
        assert other_cat_product.id not in ids

    def test_uses_active_cart_for_authenticated_customer(
        self, api_client, customer, retailer, category, brand, product
    ):
        from cart.models import Cart, CartItem
        bread = Product.objects.create(
            retailer=retailer,
            name="Eggs",
            category=category,
            brand=brand,
            price=Decimal("60.00"),
            quantity=30,
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="piece",
        )
        cart = Cart.objects.create(customer=customer, retailer=retailer)
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=product.price)

        api_client.force_authenticate(user=customer)
        url = reverse('get_frequently_bought_together', kwargs={'retailer_id': retailer.id})
        res = api_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        ids = [row['id'] for row in res.data]
        assert bread.id in ids
        assert product.id not in ids

    def test_ranks_co_purchased_companions_first(
        self, api_client, customer, retailer, address, category, brand, product
    ):
        eggs = Product.objects.create(
            retailer=retailer,
            name="Farm Eggs",
            category=category,
            brand=brand,
            price=Decimal("70.00"),
            quantity=30,
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="piece",
        )
        cereal = Product.objects.create(
            retailer=retailer,
            name="Cereal",
            category=category,
            brand=brand,
            price=Decimal("90.00"),
            quantity=30,
            track_inventory=True,
            is_active=True,
            is_available=True,
            unit="piece",
        )
        for _ in range(3):
            order = Order.objects.create(
                customer=customer,
                retailer=retailer,
                delivery_address=address,
                delivery_mode="delivery",
                payment_mode="cash",
                subtotal=Decimal("170.00"),
                total_amount=Decimal("170.00"),
                status="delivered",
            )
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                product_price=product.price,
                product_unit=product.unit,
                quantity=1,
                unit_price=product.price,
                total_price=product.price,
            )
            OrderItem.objects.create(
                order=order,
                product=eggs,
                product_name=eggs.name,
                product_price=eggs.price,
                product_unit=eggs.unit,
                quantity=1,
                unit_price=eggs.price,
                total_price=eggs.price,
            )

        url = reverse('get_frequently_bought_together', kwargs={'retailer_id': retailer.id})
        res = api_client.get(url, {'product_ids': str(product.id)})
        assert res.status_code == status.HTTP_200_OK
        ids = [row['id'] for row in res.data]
        assert eggs.id in ids
        assert cereal.id in ids
        assert ids.index(eggs.id) < ids.index(cereal.id)
