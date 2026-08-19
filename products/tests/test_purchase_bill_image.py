import io
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status

from products.models import PurchaseInvoice
from products.serializers import PurchaseInvoiceSerializer
from retailers.models import Supplier


def _tiny_png(name="bill.png"):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(200, 40, 40)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def _invoice_payload(supplier, product, invoice_number="INV-KAN60"):
    return {
        "supplier": supplier.id,
        "invoice_number": invoice_number,
        "invoice_date": "2026-08-19",
        "total_amount": "100.00",
        "paid_amount": "0.00",
        "payment_status": "UNPAID",
        "items": [
            {
                "product": product.id,
                "quantity": 10,
                "purchase_price": "10.00",
                "total": "100.00",
            }
        ],
    }


@pytest.mark.django_db
class TestPurchaseInvoiceBillImage:
    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(retailer=retailer, company_name="KAN-60 Supplier")

    def test_create_without_image_still_works(self, api_client, retailer_user, retailer, supplier, product):
        api_client.force_authenticate(user=retailer_user)
        url = reverse("erp-purchase-invoice-list")
        res = api_client.post(url, _invoice_payload(supplier, product), format="json")
        assert res.status_code == status.HTTP_201_CREATED, res.data
        assert res.data.get("bill_image") in (None, "")
        invoice = PurchaseInvoice.objects.get(id=res.data["id"])
        assert invoice.bill_image.name in ("", None)
        assert invoice.items.count() == 1

    def test_patch_bill_image_without_items_keeps_lines(
        self, api_client, retailer_user, retailer, supplier, product
    ):
        api_client.force_authenticate(user=retailer_user)
        create_res = api_client.post(
            reverse("erp-purchase-invoice-list"),
            _invoice_payload(supplier, product, invoice_number="INV-KAN60-PATCH"),
            format="json",
        )
        assert create_res.status_code == status.HTTP_201_CREATED, create_res.data
        invoice_id = create_res.data["id"]
        item_ids = [item["id"] for item in create_res.data["items"]]
        assert item_ids

        product.refresh_from_db()
        stock_before = product.quantity

        url = reverse("erp-purchase-invoice-detail", args=[invoice_id])
        res = api_client.patch(url, {"bill_image": _tiny_png()}, format="multipart")
        assert res.status_code == status.HTTP_200_OK, res.data
        assert res.data.get("bill_image")
        assert "http" in str(res.data["bill_image"]) or "/media/" in str(res.data["bill_image"])
        assert len(res.data["items"]) == 1
        assert [item["id"] for item in res.data["items"]] == item_ids

        invoice = PurchaseInvoice.objects.get(id=invoice_id)
        assert invoice.items.count() == 1
        assert invoice.bill_image.name
        product.refresh_from_db()
        assert product.quantity == stock_before

    def test_serializer_update_without_items_keeps_lines(self, retailer, supplier, product):
        request = MagicMock()
        request.user = retailer.user
        serializer = PurchaseInvoiceSerializer(
            data=_invoice_payload(supplier, product, invoice_number="INV-KAN60-SER"),
            context={"request": request, "retailer": retailer},
        )
        assert serializer.is_valid(), serializer.errors
        invoice = serializer.save(retailer=retailer)
        assert invoice.items.count() == 1
        original_item_id = invoice.items.first().id

        patch_serializer = PurchaseInvoiceSerializer(
            invoice,
            data={"bill_image": _tiny_png("replace.png")},
            partial=True,
            context={"request": request, "retailer": retailer},
        )
        assert patch_serializer.is_valid(), patch_serializer.errors
        updated = patch_serializer.save()
        assert updated.items.count() == 1
        assert updated.items.first().id == original_item_id
        assert updated.bill_image
        data = PurchaseInvoiceSerializer(updated, context={"request": request}).data
        assert data.get("bill_image")
