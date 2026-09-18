"""
OE-343 / F follow-on — optional barcode on sales-return line items.

Gated READ: echo Product.barcode only if the field already exists and
OE-313 unit has landed on the working tip. On tip 9e697ed (#147) the
unit field is absent and SalesReturnItemSerializer is still hot
(PR #145), so this slice is a no-op. Tests lock that payload shape.
Auth/tenancy unchanged. READ only. Dummy hosts only.
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
from returns.models import SalesReturn, SalesReturnItem
from returns.serializers import SalesReturnItemSerializer


PRIMARY_A = "8903153430001"
PRIMARY_B = "8903153430002"


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


def _make_category(retailer, name):
    return ProductCategory.objects.create(name=name, retailer=retailer)


def _make_product(retailer, category, name, barcode=None, **kwargs):
    fields = {
        "retailer": retailer,
        "name": name,
        "category": category,
        "barcode": barcode,
        "price": Decimal("20.00"),
        "purchase_price": Decimal("10.00"),
        "quantity": Decimal("8.000"),
        "has_batches": False,
        "track_inventory": True,
        "is_active": True,
        "is_available": True,
        "unit": "kg",
    }
    fields.update(kwargs)
    return Product.objects.create(**fields)


def _make_order(retailer, items):
    order = Order.objects.create(
        retailer=retailer,
        guest_name="Walk-in",
        delivery_mode="pickup",
        payment_mode="cash",
        status="delivered",
        source="pos",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    for product, quantity, unit_price in items:
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=product.price,
            product_unit=product.unit,
            quantity=quantity,
            unit_price=unit_price,
            total_price=quantity * unit_price,
        )
    return order


def _make_sales_return(retailer, order, created_by, items):
    sales_return = SalesReturn.objects.create(
        retailer=retailer,
        order=order,
        refund_payment_mode="cash",
        reason="OE-343 barcode no-op",
        created_by=created_by,
        refund_amount=Decimal("0.00"),
    )
    total = Decimal("0.00")
    created = []
    for product, quantity, refund_unit_price in items:
        line_total = quantity * refund_unit_price
        created.append(
            SalesReturnItem.objects.create(
                sales_return=sales_return,
                product=product,
                quantity=quantity,
                refund_unit_price=refund_unit_price,
                total_refund=line_total,
            )
        )
        total += line_total
    sales_return.refund_amount = total
    sales_return.save(update_fields=["refund_amount"])
    return sales_return, created


def _item_by_product(payload, product_id):
    items = payload.get("items") or []
    for row in items:
        if row["product"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from sales-return items")


def _return_from_list(payload, return_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == return_id:
            return row
    raise AssertionError(f"sales return {return_id} missing from payload")


def _row_by_id(payload, product_id):
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    for row in rows:
        if row["id"] == product_id:
            return row
    raise AssertionError(f"product {product_id} missing from payload")


def _assert_item_omits_gated_keys(item):
    assert "barcode" not in item
    assert "unit" not in item
    assert "product_name" in item


@pytest.mark.django_db
class TestSalesReturnItemBarcodeNoop:
    def test_gates_product_has_barcode_item_and_unit_do_not(self):
        assert any(f.name == "barcode" for f in Product._meta.get_fields())
        assert not any(f.name == "barcode" for f in SalesReturnItem._meta.get_fields())
        fields = set(SalesReturnItemSerializer.Meta.fields)
        assert "barcode" not in fields
        assert "unit" not in fields

    def test_list_and_detail_omit_barcode_even_when_product_has_one(self, api_client):
        owner, shop = _make_retailer("oe343_hit_own", "OE343 Barcode Shop")
        category = _make_category(shop, "OE343 Barcode Cat")
        coded = _make_product(shop, category, "OE343 Coded Atta", barcode=PRIMARY_A)
        blank = _make_product(shop, category, "OE343 Blank Atta", barcode="")
        missing = _make_product(shop, category, "OE343 Null Atta", barcode=None)
        order = _make_order(
            shop,
            [
                (coded, Decimal("2.000"), Decimal("10.00")),
                (blank, Decimal("1.000"), Decimal("8.00")),
                (missing, Decimal("1.000"), Decimal("5.00")),
            ],
        )
        sales_return, _items = _make_sales_return(
            shop,
            order,
            owner,
            [
                (coded, Decimal("1.000"), Decimal("10.00")),
                (blank, Decimal("1.000"), Decimal("8.00")),
                (missing, Decimal("1.000"), Decimal("5.00")),
            ],
        )

        api_client.force_authenticate(user=owner)
        listed = api_client.get(reverse("get_retailer_products"))
        coded_detail = api_client.get(reverse("get_product_detail", args=[coded.id]))
        return_list = api_client.get(reverse("sales-return-list"))
        return_detail = api_client.get(
            reverse("sales-return-detail", args=[sales_return.id])
        )

        assert listed.status_code == status.HTTP_200_OK
        assert coded_detail.status_code == status.HTTP_200_OK
        assert return_list.status_code == status.HTTP_200_OK
        assert return_detail.status_code == status.HTTP_200_OK

        catalog = _row_by_id(listed.data, coded.id)
        assert catalog["barcode"] == PRIMARY_A
        assert coded_detail.data["barcode"] == PRIMARY_A

        list_return = _return_from_list(return_list.data, sales_return.id)
        for product in (coded, blank, missing):
            for payload in (return_detail.data, list_return):
                item = _item_by_product(payload, product.id)
                _assert_item_omits_gated_keys(item)
                assert item["product_name"] == product.name

    def test_write_payload_barcode_is_ignored(self, api_client):
        owner, shop = _make_retailer("oe343_write_own", "OE343 Write Shop")
        category = _make_category(shop, "OE343 Write Cat")
        product = _make_product(
            shop, category, "OE343 Write Atta", barcode=PRIMARY_B
        )
        order = _make_order(shop, [(product, Decimal("2.000"), Decimal("10.00"))])
        order_item = order.items.get(product=product)

        api_client.force_authenticate(user=owner)
        created = api_client.post(
            reverse("sales-return-list"),
            {
                "order_id": order.id,
                "refund_payment_mode": "cash",
                "reason": "OE-343 write ignore",
                "items": [
                    {
                        "product_id": product.id,
                        "order_item_id": order_item.id,
                        "quantity": 1,
                        "refund_unit_price": "10.00",
                        "barcode": "9999999999999",
                    }
                ],
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        item = _item_by_product(created.data, product.id)
        _assert_item_omits_gated_keys(item)
        product.refresh_from_db()
        assert product.barcode == PRIMARY_B

    def test_unauthenticated_denied(self, api_client):
        owner, shop = _make_retailer("oe343_auth_own", "OE343 Auth Shop")
        category = _make_category(shop, "OE343 Auth Cat")
        product = _make_product(
            shop, category, "OE343 Auth Rice", barcode=PRIMARY_A
        )
        order = _make_order(shop, [(product, Decimal("1.000"), Decimal("10.00"))])
        sales_return, _items = _make_sales_return(
            shop,
            order,
            owner,
            [(product, Decimal("1.000"), Decimal("10.00"))],
        )

        listed = api_client.get(reverse("sales-return-list"))
        detail = api_client.get(
            reverse("sales-return-detail", args=[sales_return.id])
        )
        assert listed.status_code == status.HTTP_401_UNAUTHORIZED
        assert detail.status_code == status.HTTP_401_UNAUTHORIZED

    def test_return_stays_shop_scoped(self, api_client):
        owner_a, shop_a = _make_retailer("oe343_ten_a", "OE343 Tenant A")
        owner_b, shop_b = _make_retailer("oe343_ten_b", "OE343 Tenant B")
        cat_a = _make_category(shop_a, "OE343 A Cat")
        cat_b = _make_category(shop_b, "OE343 B Cat")
        product_a = _make_product(shop_a, cat_a, "OE343 A SKU", barcode=PRIMARY_A)
        product_b = _make_product(shop_b, cat_b, "OE343 B SKU", barcode=PRIMARY_B)
        ret_a, _ = _make_sales_return(
            shop_a,
            _make_order(shop_a, [(product_a, Decimal("1.000"), Decimal("10.00"))]),
            owner_a,
            [(product_a, Decimal("1.000"), Decimal("10.00"))],
        )
        ret_b, _ = _make_sales_return(
            shop_b,
            _make_order(shop_b, [(product_b, Decimal("1.000"), Decimal("10.00"))]),
            owner_b,
            [(product_b, Decimal("1.000"), Decimal("10.00"))],
        )

        api_client.force_authenticate(user=owner_b)
        listed = api_client.get(reverse("sales-return-list"))
        foreign = api_client.get(reverse("sales-return-detail", args=[ret_a.id]))
        own = api_client.get(reverse("sales-return-detail", args=[ret_b.id]))

        assert listed.status_code == status.HTTP_200_OK
        assert foreign.status_code == status.HTTP_404_NOT_FOUND
        assert own.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in listed.data["results"]}
        assert ret_a.id not in ids
        assert ret_b.id in ids
        _assert_item_omits_gated_keys(_item_by_product(own.data, product_b.id))
