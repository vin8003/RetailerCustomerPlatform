"""
OE-301 / F follow-on — delivery_fee + discount_amount on order list.

Same Order.delivery_fee / Order.discount_amount as order detail.
Null stays null (do not omit). Auth/tenancy unchanged. READ only.
This slice does not touch ProductSearchSerializer Meta or POS no_page.
"""
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from customers.models import CustomerAddress, CustomerProfile
from orders.models import Order
from orders.serializers import OrderDetailSerializer, OrderListSerializer
from products.serializers import ProductSearchSerializer
from retailers.models import RetailerProfile
from retailers.organization import ensure_organization_for_profile

FEE_PRESENT = Decimal("15.50")
DISCOUNT_PRESENT = Decimal("7.25")

# Frozen from PR #130 tip (d022f37). This sibling must not rewrite search Meta.
OE300_SEARCH_META_FIELDS = [
    "id",
    "name",
    "price",
    "app_price",
    "discounted_price",
    "original_price",
    "unit",
    "image",
    "category_name",
    "brand_name",
    "barcode",
    "is_featured",
    "is_active",
    "is_seasonal",
    "product_group",
    "track_inventory",
    "quantity",
    "saleable_quantity",
    "margin_percent",
    "has_batches",
    "batches",
    "is_parent_bulk",
    "parent_bulk_product",
    "conversion_factor",
    "fractional_children",
    "group_variants",
]

# Frozen POS no_page row keys from products/views.py at #130 tip.
OE300_POS_NOPAGE_ROW_KEYS = [
    "id",
    "name",
    "price",
    "app_price",
    "discounted_price",
    "original_price",
    "quantity",
    "saleable_quantity",
    "track_inventory",
    "unit",
    "image",
    "category_name",
    "brand_name",
    "barcode",
    "is_active",
    "is_seasonal",
    "product_group",
    "has_batches",
    "batches",
    "group_variants",
    "is_parent_bulk",
    "parent_bulk_product",
    "conversion_factor",
    "fractional_children",
]


def _dec(value):
    if value is None:
        return None
    return Decimal(str(value))


def _rows(payload):
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    return payload


def _row_by_id(payload, order_id):
    for row in _rows(payload):
        if row["id"] == order_id:
            return row
    raise AssertionError("order {0} missing from list payload".format(order_id))


def _assert_fee_parity(list_row, detail_row):
    assert "delivery_fee" in list_row
    assert "discount_amount" in list_row
    assert _dec(list_row["delivery_fee"]) == _dec(detail_row["delivery_fee"])
    assert _dec(list_row["discount_amount"]) == _dec(detail_row["discount_amount"])


def _make_retailer(username, shop_name):
    user = User.objects.create_user(
        username=username,
        email="{0}@test.com".format(username),
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
    ensure_organization_for_profile(profile, name="{0} Org".format(shop_name))
    return user, profile


def _make_customer(username):
    user = User.objects.create_user(
        username=username,
        email="{0}@test.com".format(username),
        password="TestPass123!",
        user_type="customer",
        is_active=True,
    )
    CustomerProfile.objects.create(user=user)
    return user


def _make_address(customer):
    return CustomerAddress.objects.create(
        customer=customer,
        title="Home",
        address_type="home",
        address_line1="456 Test St",
        city="TestCity",
        state="TestState",
        pincode="123456",
        is_default=True,
    )


def _make_order(customer, retailer, address, **kwargs):
    fields = {
        "customer": customer,
        "retailer": retailer,
        "delivery_address": address,
        "delivery_mode": "delivery",
        "payment_mode": "cash",
        "subtotal": Decimal("200.00"),
        "total_amount": Decimal("200.00"),
        "status": "pending",
    }
    fields.update(kwargs)
    return Order.objects.create(**fields)


@pytest.mark.django_db
class TestOrderListFeeDiscountOE301:
    def test_list_echoes_present_fees_matching_detail(self, order):
        order.delivery_fee = FEE_PRESENT
        order.discount_amount = DISCOUNT_PRESENT
        order.save(update_fields=["delivery_fee", "discount_amount"])

        list_data = OrderListSerializer(order).data
        detail_data = OrderDetailSerializer(order).data
        _assert_fee_parity(list_data, detail_data)
        assert _dec(list_data["delivery_fee"]) == FEE_PRESENT
        assert _dec(list_data["discount_amount"]) == DISCOUNT_PRESENT

    def test_list_echoes_null_fees_matching_detail(self, order):
        order.delivery_fee = None
        order.discount_amount = None

        list_data = OrderListSerializer(order).data
        detail_data = OrderDetailSerializer(order).data
        _assert_fee_parity(list_data, detail_data)
        assert list_data["delivery_fee"] is None
        assert list_data["discount_amount"] is None
        assert detail_data["delivery_fee"] is None
        assert detail_data["discount_amount"] is None

    def test_retailer_current_list_matches_detail_http(
        self, api_client, retailer_user, retailer, order
    ):
        order.delivery_fee = FEE_PRESENT
        order.discount_amount = DISCOUNT_PRESENT
        order.save(update_fields=["delivery_fee", "discount_amount"])

        api_client.force_authenticate(user=retailer_user)
        listed = api_client.get(reverse("get_current_orders"))
        detail = api_client.get(reverse("get_order_detail", args=[order.id]))
        history = api_client.get(reverse("get_order_history"))

        assert listed.status_code == status.HTTP_200_OK
        assert detail.status_code == status.HTTP_200_OK
        assert history.status_code == status.HTTP_200_OK
        _assert_fee_parity(_row_by_id(listed.data, order.id), detail.data)
        _assert_fee_parity(_row_by_id(history.data, order.id), detail.data)

    def test_unauthenticated_order_list_denied(self, api_client):
        listed = api_client.get(reverse("get_current_orders"))
        history = api_client.get(reverse("get_order_history"))
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert history.status_code == status.HTTP_401_UNAUTHORIZED

    def test_order_list_stays_shop_scoped(self, api_client):
        customer_a = _make_customer("oe301_cust_a")
        customer_b = _make_customer("oe301_cust_b")
        owner_a, shop_a = _make_retailer("oe301_ten_a", "OE301 Tenant A")
        owner_b, shop_b = _make_retailer("oe301_ten_b", "OE301 Tenant B")
        order_a = _make_order(
            customer_a,
            shop_a,
            _make_address(customer_a),
            delivery_fee=FEE_PRESENT,
            discount_amount=DISCOUNT_PRESENT,
        )
        order_b = _make_order(
            customer_b,
            shop_b,
            _make_address(customer_b),
            delivery_fee=Decimal("3.00"),
            discount_amount=Decimal("1.00"),
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("get_current_orders"))
        detail_a = api_client.get(reverse("get_order_detail", args=[order_a.id]))
        detail_b = api_client.get(reverse("get_order_detail", args=[order_b.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert detail_a.status_code == status.HTTP_404_NOT_FOUND
        assert detail_b.status_code == status.HTTP_200_OK
        list_ids = {row["id"] for row in _rows(listed.data)}
        assert order_a.id not in list_ids
        assert order_b.id in list_ids
        _assert_fee_parity(_row_by_id(listed.data, order_b.id), detail_b.data)

    def test_search_meta_and_pos_views_untouched(self):
        assert list(ProductSearchSerializer.Meta.fields) == OE300_SEARCH_META_FIELDS

        views_path = Path(__file__).resolve().parents[2] / "products" / "views.py"
        views_src = views_path.read_text()
        start = views_src.index("if request.query_params.get('no_page') == 'true':")
        end = views_src.index("# Apply expensive annotations for normal paginated path")
        nopage_block = views_src[start:end]

        assert "OrderListSerializer" not in views_src
        assert "delivery_fee" not in nopage_block
        assert "discount_amount" not in nopage_block
        for key in OE300_POS_NOPAGE_ROW_KEYS:
            assert "'{0}'".format(key) in nopage_block
