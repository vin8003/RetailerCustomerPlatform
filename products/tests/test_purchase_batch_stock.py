"""
Regression: purchase inward must land on the same stock counter POS sells from.

Shop Easy saw ENSHINE ULTRA SOFT TOOTHBRUSH 1N jump from
  Purchase Updated +96 → new balance 98
to
  POS Sale -1 → new balance -1
because create/update wrote Product.quantity via F() and never touched
ProductBatch.quantity. POS then deducted the stale batch (0) and
sync_inventory_from_batches overwrote SKU qty to -1.
"""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.urls import reverse
from rest_framework import status

from products.models import Product, ProductBatch, ProductInventoryLog
from products.serializers import PurchaseInvoiceSerializer
from retailers.models import Supplier


@pytest.mark.django_db
class TestPurchaseBatchStockLockstep:
    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer, company_name="Hindustan Distributors"
        )

    @pytest.fixture
    def batched_brush(self, retailer, category, brand):
        product = Product.objects.create(
            retailer=retailer,
            name="ENSHINE ULTRA SOFT TOOTHBRUSH 1N",
            category=category,
            brand=brand,
            price=Decimal("45.00"),
            purchase_price=Decimal("22.00"),
            quantity=Decimal("2"),
            track_inventory=True,
            has_batches=True,
            unit="piece",
        )
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number="INITIAL-STOCK",
            price=Decimal("45.00"),
            purchase_price=Decimal("22.00"),
            quantity=Decimal("2"),
            is_active=True,
        )
        return product

    def _invoice_payload(self, supplier, product, quantity, invoice_number, paid="0.00"):
        return {
            "supplier": supplier.id,
            "invoice_number": invoice_number,
            "invoice_date": "2026-08-31",
            "total_amount": str(Decimal(str(quantity)) * Decimal("22.00")),
            "paid_amount": paid,
            "payment_status": "UNPAID",
            "items": [
                {
                    "product": product.id,
                    "quantity": quantity,
                    "purchase_price": "22.00",
                    "total": str(Decimal(str(quantity)) * Decimal("22.00")),
                }
            ],
        }

    def test_purchase_update_then_pos_sale_does_not_go_negative(
        self, api_client, retailer_user, retailer, supplier, batched_brush
    ):
        api_client.force_authenticate(user=retailer_user)
        request = MagicMock()
        request.user = retailer_user

        # 1. Create an empty-ish invoice then UPDATE qty to 96 (the screenshot path)
        create = PurchaseInvoiceSerializer(
            data=self._invoice_payload(supplier, batched_brush, 0, "L-2464"),
            context={"request": request, "retailer": retailer},
        )
        assert create.is_valid(), create.errors
        invoice = create.save(retailer=retailer)

        update = PurchaseInvoiceSerializer(
            invoice,
            data=self._invoice_payload(supplier, batched_brush, 96, "L-2464"),
            context={"request": request, "retailer": retailer},
        )
        assert update.is_valid(), update.errors
        update.save()

        batched_brush.refresh_from_db()
        batch = batched_brush.batches.get(batch_number="INITIAL-STOCK")
        assert batched_brush.quantity == Decimal("98")
        assert batch.quantity == Decimal("98")

        added = ProductInventoryLog.objects.filter(
            product=batched_brush, log_type="added", reason__contains="L-2464"
        ).latest("id")
        assert added.new_quantity == Decimal("98")
        assert added.quantity_change == Decimal("96")

        # 2. POS sells 1 unit against that batch
        url = reverse("create_pos_order")
        res = api_client.post(
            url,
            {
                "subtotal": 45.0,
                "total_amount": 45.0,
                "items": [
                    {
                        "product_id": batched_brush.id,
                        "batch_id": batch.id,
                        "quantity": 1,
                        "unit_price": 45.0,
                    }
                ],
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED, res.data

        batched_brush.refresh_from_db()
        batch.refresh_from_db()
        assert batched_brush.quantity == Decimal("97")
        assert batch.quantity == Decimal("97")

        sold = ProductInventoryLog.objects.filter(
            product=batched_brush, log_type="sold"
        ).latest("id")
        assert sold.previous_quantity == Decimal("98")
        assert sold.new_quantity == Decimal("97")
        assert sold.quantity_change == Decimal("-1")

    def test_purchase_create_increments_default_batch(
        self, retailer_user, retailer, supplier, batched_brush
    ):
        request = MagicMock()
        request.user = retailer_user
        serializer = PurchaseInvoiceSerializer(
            data=self._invoice_payload(supplier, batched_brush, 10, "L-2500"),
            context={"request": request, "retailer": retailer},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save(retailer=retailer)

        batched_brush.refresh_from_db()
        batch = batched_brush.batches.get(batch_number="INITIAL-STOCK")
        assert batched_brush.quantity == Decimal("12")
        assert batch.quantity == Decimal("12")

    def test_unbatched_product_purchase_still_adds_sku_qty(
        self, retailer_user, retailer, supplier, product
    ):
        request = MagicMock()
        request.user = retailer_user
        serializer = PurchaseInvoiceSerializer(
            data=self._invoice_payload(supplier, product, 10, "L-UNBATCHED"),
            context={"request": request, "retailer": retailer},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save(retailer=retailer)

        product.refresh_from_db()
        assert product.quantity == Decimal("60")
