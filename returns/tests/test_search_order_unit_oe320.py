"""
OE-320 / F follow-on — unit on sales-return search_order picker.

Same value as product.unit. Empty/null stays empty/null
(no invented 'piece' on read). Auth/tenancy unchanged. READ only.
Does not touch SalesReturnItemSerializer, ProductSearchSerializer, or POS.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from orders.models import Order, OrderItem
from products.models import Product, ProductCategory
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile


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


def _make_customer(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="customer",
        is_active=True,
    )


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_product(retailer, category, name, unit="piece", **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "price": Decimal("20.00"),
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": unit,
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _make_delivered_order(retailer, customer, lines):
    """lines: iterable of (product, quantity, snapshot_unit=None)."""
    order = Order.objects.create(
        retailer=retailer,
        customer=customer,
        subtotal=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        status="delivered",
        payment_mode="cash",
    )
    subtotal = Decimal("0.00")
    for line in lines:
        product, quantity = line[0], line[1]
        snapshot_unit = line[2] if len(line) > 2 else product.unit
        qty = Decimal(str(quantity))
        line_total = product.price * qty
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=snapshot_unit,
            quantity=qty,
            unit_price=product.price,
            total_price=line_total,
        )
        subtotal += line_total
    order.subtotal = subtotal
    order.total_amount = subtotal
    order.save(update_fields=["subtotal", "total_amount"])
    return order


def _search_order(api_client, query):
    return api_client.get(reverse("sales-return-search-order"), {"query": query})


def _picker_item(payload, product_id):
    for order in payload:
        for item in order.get("items") or []:
            if item["product_id"] == product_id:
                return item
    raise AssertionError(f"product {product_id} missing from picker payload")


@pytest.mark.django_db
class TestSearchOrderPickerUnit:
    def test_picker_echoes_product_unit(self, api_client):
        owner, shop = _make_retailer("oe320_hit_own", "OE320 Unit Shop")
        customer = _make_customer("oe320_hit_cust")
        category = _make_category(shop, "OE320 Unit Cat")
        kg = _make_product(shop, category, "OE320 Atta", unit="kg")
        pack = _make_product(shop, category, "OE320 Biscuits", unit="pack")
        default = _make_product(shop, category, "OE320 Piece Default", unit="piece")
        order = _make_delivered_order(
            shop,
            customer,
            (
                (kg, 2),
                (pack, 3),
                (default, 1),
            ),
        )

        api_client.force_authenticate(user=owner)
        response = _search_order(api_client, order.order_number)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["id"] == order.id
        for product, expected in ((kg, "kg"), (pack, "pack"), (default, "piece")):
            row = _picker_item(response.data, product.id)
            assert "unit" in row
            assert row["unit"] == expected
            assert row["unit"] == product.unit

    def test_empty_unit_stays_empty(self, api_client):
        owner, shop = _make_retailer("oe320_empty_own", "OE320 Empty Shop")
        customer = _make_customer("oe320_empty_cust")
        category = _make_category(shop, "OE320 Empty Cat")
        product = _make_product(shop, category, "OE320 Blank Unit", unit="kg")
        Product.objects.filter(pk=product.id).update(unit="")
        product.refresh_from_db()
        assert product.unit == ""
        order = _make_delivered_order(
            shop,
            customer,
            ((product, 1, "kg"),),
        )

        api_client.force_authenticate(user=owner)
        response = _search_order(api_client, order.order_number)

        assert response.status_code == status.HTTP_200_OK
        row = _picker_item(response.data, product.id)
        assert row["unit"] == ""
        assert row["unit"] == product.unit
        assert row["unit"] != "piece"

    def test_echoes_product_unit_not_order_item_snapshot(self, api_client):
        owner, shop = _make_retailer("oe320_snap_own", "OE320 Snapshot Shop")
        customer = _make_customer("oe320_snap_cust")
        category = _make_category(shop, "OE320 Snapshot Cat")
        product = _make_product(shop, category, "OE320 Live Unit", unit="liter")
        order = _make_delivered_order(
            shop,
            customer,
            ((product, 1, "piece"),),
        )
        order_item = order.items.get(product=product)
        assert order_item.product_unit == "piece"
        assert product.unit == "liter"

        api_client.force_authenticate(user=owner)
        response = _search_order(api_client, order.order_number)

        assert response.status_code == status.HTTP_200_OK
        row = _picker_item(response.data, product.id)
        assert row["unit"] == "liter"
        assert row["unit"] != order_item.product_unit

    def test_unauthenticated_denied(self, api_client):
        _owner, shop = _make_retailer("oe320_auth_own", "OE320 Auth Shop")
        customer = _make_customer("oe320_auth_cust")
        category = _make_category(shop, "OE320 Auth Cat")
        product = _make_product(shop, category, "OE320 Auth Rice", unit="kg")
        order = _make_delivered_order(shop, customer, ((product, 1),))

        anon = _search_order(api_client, order.order_number)
        assert anon.status_code == status.HTTP_401_UNAUTHORIZED

    def test_picker_stays_shop_scoped(self, api_client):
        _owner_a, shop_a = _make_retailer("oe320_ten_a", "OE320 Tenant A")
        owner_b, shop_b = _make_retailer("oe320_ten_b", "OE320 Tenant B")
        customer_a = _make_customer("oe320_ten_cust_a")
        customer_b = _make_customer("oe320_ten_cust_b")
        cat_a = _make_category(shop_a, "OE320 A Cat")
        cat_b = _make_category(shop_b, "OE320 B Cat")
        product_a = _make_product(shop_a, cat_a, "OE320 A SKU", unit="liter")
        product_b = _make_product(shop_b, cat_b, "OE320 B SKU", unit="dozen")
        order_a = _make_delivered_order(shop_a, customer_a, ((product_a, 1),))
        order_b = _make_delivered_order(shop_b, customer_b, ((product_b, 2),))

        api_client.force_authenticate(user=owner_b)
        other = _search_order(api_client, order_a.order_number)
        own = _search_order(api_client, order_b.order_number)

        assert other.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        assert own.data[0]["id"] == order_b.id
        assert _picker_item(own.data, product_b.id)["unit"] == "dozen"
        with pytest.raises(AssertionError):
            _picker_item(own.data, product_a.id)

    def test_missing_query_unchanged(self, api_client):
        owner, _shop = _make_retailer("oe320_q_own", "OE320 Query Shop")
        api_client.force_authenticate(user=owner)
        response = api_client.get(reverse("sales-return-search-order"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Query parameter is required"
