from rest_framework import serializers
from .models import SalesReturn, SalesReturnItem, PurchaseReturn, PurchaseReturnItem

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

    class Meta:
        model = PurchaseReturnItem
        fields = ['id', 'product', 'product_name', 'batch', 'batch_number', 'quantity', 'purchase_price', 'total']

class PurchaseReturnSerializer(serializers.ModelSerializer):
    items = PurchaseReturnItemSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    processed_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = PurchaseReturn
        fields = ['id', 'return_number', 'supplier', 'supplier_name', 'invoice', 'invoice_number', 'total_amount', 'notes', 'return_date', 'processed_by_name', 'created_at', 'items']
        read_only_fields = ['id', 'return_number', 'created_at', 'total_amount', 'return_date']
