"""Inventory ledger row payload for GET /api/products/erp/inventory-ledger/."""
from django.core.exceptions import FieldDoesNotExist

from products.models import ProductInventoryLog


def log_has_expiry_date_field(model=None):
    """True when ProductInventoryLog (or a dummy stand-in) declares expiry_date."""
    target = ProductInventoryLog if model is None else model
    meta = getattr(target, "_meta", None)
    if meta is None:
        return False
    try:
        meta.get_field("expiry_date")
    except FieldDoesNotExist:
        return False
    return True


def attach_ledger_expiry_date(data, instance, model=None):
    """Echo expiry_date only when the model field exists. Null stays null."""
    if not log_has_expiry_date_field(model):
        return data
    data["expiry_date"] = getattr(instance, "expiry_date", None)
    return data


class InventoryLedgerRowSerializer:
    """One ProductInventoryLog row. Optional expiry_date only if that field exists."""

    def __init__(self, instance, many=False):
        self.instance = instance
        self.many = many

    @property
    def data(self):
        if self.many:
            return [self._row(item) for item in self.instance]
        return self._row(self.instance)

    def _row(self, log):
        created_by = log.created_by
        row = {
            "id": log.id,
            "product_id": log.product_id,
            "product_name": log.product.name,
            "barcode": log.product.barcode,
            "log_type": log.log_type,
            "batch_id": log.batch_id,
            "quantity_change": log.quantity_change,
            "previous_quantity": log.previous_quantity,
            "new_quantity": log.new_quantity,
            "reason": log.reason,
            "created_at": log.created_at,
            "created_by": created_by.get_full_name() if created_by else "System",
        }
        return attach_ledger_expiry_date(row, log)
