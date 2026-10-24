"""OE-325 order notes, OE-327 sales-return notes, OE-337 supplier email."""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from authentication.models import User
from orders.models import Order, OrderItem
from retailers.models import OrgRole, OrgStaffMembership, Supplier
from retailers.organization import ensure_organization_for_profile
from returns.models import SalesReturn


def _staff(org, username, permissions):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="TestPass123!",
        user_type="retailer",
        is_active=True,
    )
    role = OrgRole.objects.create(
        organization=org,
        slug=f"role_{username}",
        name=f"Role {username}",
        permissions=list(permissions),
        is_system=False,
    )
    OrgStaffMembership.objects.create(organization=org, user=user, role=role, is_active=True)
    return user


@pytest.fixture
def order(retailer, customer, product):
    order = Order.objects.create(
        customer=customer,
        retailer=retailer,
        subtotal=Decimal("200.00"),
        total_amount=Decimal("200.00"),
        status="delivered",
        payment_mode="cash",
        special_instructions="Ring twice",
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
class TestOrderNotesOE325:
    def test_owner_sets_notes_and_retailer_detail_returns_them(self, api_client, retailer_user, order):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("update_order_notes", args=[order.id])
        response = api_client.patch(url, {"notes": "  Call before delivery  "}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["notes"] == "Call before delivery"
        order.refresh_from_db()
        assert order.notes == "Call before delivery"

        detail = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert detail.status_code == status.HTTP_200_OK
        assert detail.data["notes"] == "Call before delivery"
        assert detail.data["special_instructions"] == "Ring twice"

    def test_customer_never_sees_or_edits_notes(self, api_client, customer, order):
        order.notes = "Customer was rude"
        order.save(update_fields=["notes"])
        api_client.force_authenticate(user=customer)

        detail = api_client.get(reverse("get_order_detail", args=[order.id]))
        assert detail.status_code == status.HTTP_200_OK
        assert "notes" not in detail.data
        assert detail.data["special_instructions"] == "Ring twice"

        response = api_client.patch(
            reverse("update_order_notes", args=[order.id]), {"notes": "x"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        order.refresh_from_db()
        assert order.notes == "Customer was rude"

    def test_staff_without_orders_update_gets_403(self, api_client, retailer, order):
        org = ensure_organization_for_profile(retailer)
        reader = _staff(org, "notes_reader", ["orders.read"])
        api_client.force_authenticate(user=reader)
        response = api_client.patch(
            reverse("update_order_notes", args=[order.id]), {"notes": "x"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_blank_clears_and_too_long_is_rejected(self, api_client, retailer_user, order):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("update_order_notes", args=[order.id])
        assert api_client.patch(url, {"notes": "keep"}, format="json").status_code == 200
        assert api_client.patch(url, {"notes": "   "}, format="json").data["notes"] == ""
        too_long = api_client.patch(url, {"notes": "a" * 1001}, format="json")
        assert too_long.status_code == status.HTTP_400_BAD_REQUEST
        bad_type = api_client.patch(url, {"notes": ["a"]}, format="json")
        assert bad_type.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestSalesReturnNotesOE327:
    def _payload(self, order, product, **extra):
        item = order.items.first()
        return {
            "order_id": order.id,
            "refund_payment_mode": "cash",
            "reason": "Damaged pack",
            "items": [{
                "product_id": product.id,
                "order_item_id": item.id,
                "quantity": 1,
                "refund_unit_price": str(product.price),
            }],
            **extra,
        }

    def test_notes_are_stored_separately_from_reason(self, api_client, retailer_user, order, product):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.post(
            "/api/returns/sales/",
            self._payload(order, product, notes=" Refunded in cash at counter "),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["notes"] == "Refunded in cash at counter"
        assert response.data["reason"] == "Damaged pack"

        sr = SalesReturn.objects.get(id=response.data["id"])
        assert sr.notes == "Refunded in cash at counter"
        detail = api_client.get(f"/api/returns/sales/{sr.id}/")
        assert detail.data["notes"] == "Refunded in cash at counter"

    def test_notes_default_to_blank(self, api_client, retailer_user, order, product):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.post("/api/returns/sales/", self._payload(order, product), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["notes"] == ""

    def test_too_long_notes_rejected_without_a_return(self, api_client, retailer_user, order, product):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.post(
            "/api/returns/sales/", self._payload(order, product, notes="a" * 1001), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SalesReturn.objects.exists()


@pytest.mark.django_db
class TestSupplierEmailOE337:
    def test_create_list_detail_and_patch_email(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        created = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Mail Traders", "email": "orders@mailtraders.in"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        assert created.data["email"] == "orders@mailtraders.in"

        listing = api_client.get(reverse("erp-supplier-list"))
        rows = listing.data["results"] if isinstance(listing.data, dict) else listing.data
        assert [r["email"] for r in rows if r["id"] == created.data["id"]] == ["orders@mailtraders.in"]

        url = reverse("erp-supplier-detail", args=[created.data["id"]])
        assert api_client.patch(url, {"email": ""}, format="json").data["email"] == ""
        assert Supplier.objects.get(id=created.data["id"]).email == ""

    def test_invalid_email_rejected(self, api_client, retailer_user, retailer):
        api_client.force_authenticate(user=retailer_user)
        response = api_client.post(
            reverse("erp-supplier-list"),
            {"company_name": "Bad Mail", "email": "not-an-email"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "email" in response.data
