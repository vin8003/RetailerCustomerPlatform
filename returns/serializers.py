from rest_framework import serializers
from .models import SalesReturn, SalesReturnItem, PurchaseReturn, PurchaseReturnItem


def product_hsn_code(product):
    """Echo Product.hsn_code when the attribute exists; otherwise None.

    Product has no HSN column on this stack (KAN-57 / OE-57 rebuild is out of
    scope). Missing attribute, missing product, and stored null all pass through
    as None. Empty string stays empty — do not invent an HSN.
    """
    if product is None:
        return None
    return getattr(product, "hsn_code", None)


class SalesReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)

    class Meta:
        model = SalesReturnItem
        fields = ['id', 'product', 'product_name', 'batch', 'batch_number', 'quantity', 'refund_unit_price', 'total_refund']

class SalesReturnSerializer(serializers.ModelSerializer):
    items = SalesReturnItemSerializer(many=True, read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    customer_name = serializers.SerializerMethodField()
    processed_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = SalesReturn
        fields = ['id', 'order', 'order_number', 'customer_name', 'refund_amount', 'refund_payment_mode', 'reason', 'processed_by_name', 'created_at', 'items']
        read_only_fields = ['id', 'created_at', 'refund_amount']

    def get_customer_name(self, obj):
        if obj.customer:
            return obj.customer.get_full_name()
        if obj.order and obj.order.guest_name:
            return obj.order.guest_name
        return "Walk-in"

class PurchaseReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    # OE-339: optional echo when Product.hsn_code exists. Null/missing → null.
    hsn_code = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReturnItem
        fields = [
            'id', 'product', 'product_name', 'hsn_code', 'batch', 'batch_number',
            'quantity', 'purchase_price', 'total',
        ]
        read_only_fields = ['id', 'hsn_code']

    def get_hsn_code(self, obj):
        return product_hsn_code(getattr(obj, 'product', None))

class PurchaseReturnSerializer(serializers.ModelSerializer):
    items = PurchaseReturnItemSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    processed_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = PurchaseReturn
        fields = ['id', 'return_number', 'supplier', 'supplier_name', 'invoice', 'invoice_number', 'total_amount', 'notes', 'return_date', 'processed_by_name', 'created_at', 'items']
        read_only_fields = ['id', 'return_number', 'created_at', 'total_amount', 'return_date']
