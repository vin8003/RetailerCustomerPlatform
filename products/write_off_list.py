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


def serialize_write_off_list_row(log):
    """Same ledger row keys as the prior hand-built dict, plus remarks.

    Keeps Decimal / datetime objects so OE-141 / OE-315 response.data stays
    equivalent. remarks is the only new key.
    """
    product = log.product
    user = log.created_by
    return {
        'id': log.id,
        'product_id': log.product_id,
        'product_name': product.name,
        'barcode': product.barcode,
        'log_type': log.log_type,
        'batch_id': log.batch_id,
        'quantity_change': log.quantity_change,
        'previous_quantity': log.previous_quantity,
        'new_quantity': log.new_quantity,
        'reason': log.reason,
        'remarks': inventory_log_remarks(log),
        'created_at': log.created_at,
        'created_by': user.get_full_name() if user else 'System',
    }


class WriteOffListSerializer(serializers.BaseSerializer):
    """Ledger / write-off list row. Optional remarks via inventory_log_remarks."""

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

    def to_representation(self, instance):
        return serialize_write_off_list_row(instance)
