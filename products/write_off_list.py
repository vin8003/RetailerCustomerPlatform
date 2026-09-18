"""
OE-358 / F follow-on — optional remarks on write-off list rows.

READ echo only. ProductInventoryLog has reason, not remarks, on this stack.
Do not invent a remarks column or write path.
"""
from rest_framework import serializers

from products.models import ProductInventoryLog


def inventory_log_remarks(log):
    """Echo ProductInventoryLog.remarks when the attribute exists.

    Missing attribute, missing log, and stored null all pass through as None.
    Empty string stays empty — do not invent remarks from reason.
    """
    if log is None:
        return None
    return getattr(log, 'remarks', None)


class WriteOffListSerializer(serializers.ModelSerializer):
    """Ledger / write-off list row. Same identity keys as the hand-built dict."""

    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    barcode = serializers.CharField(
        source='product.barcode',
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    remarks = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = ProductInventoryLog
        fields = [
            'id',
            'product_id',
            'product_name',
            'barcode',
            'log_type',
            'batch_id',
            'quantity_change',
            'previous_quantity',
            'new_quantity',
            'reason',
            'remarks',
            'created_at',
            'created_by',
        ]
        read_only_fields = fields

    def get_remarks(self, obj):
        return inventory_log_remarks(obj)

    def get_created_by(self, obj):
        user = obj.created_by
        return user.get_full_name() if user else 'System'

    def to_representation(self, instance):
        # Keep the prior hand-built ledger types (Decimal / datetime objects)
        # so OE-141 / OE-315 response.data stays equivalent. remarks is the
        # only new key.
        product = instance.product
        user = instance.created_by
        return {
            'id': instance.id,
            'product_id': instance.product_id,
            'product_name': product.name,
            'barcode': product.barcode,
            'log_type': instance.log_type,
            'batch_id': instance.batch_id,
            'quantity_change': instance.quantity_change,
            'previous_quantity': instance.previous_quantity,
            'new_quantity': instance.new_quantity,
            'reason': instance.reason,
            'remarks': inventory_log_remarks(instance),
            'created_at': instance.created_at,
            'created_by': user.get_full_name() if user else 'System',
        }
