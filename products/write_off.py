"""
OE-141 / F-0032 — damage / expiry / spoilage write-off.

EXTEND Product.quantity + ProductBatch + ProductInventoryLog.
Does not add StockMovement or a second on-hand cache.
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction

from products.models import Product, ProductBatch, ProductInventoryLog

REASON_DAMAGE = 'damage'
REASON_EXPIRY = 'expiry'
REASON_SPOILAGE = 'spoilage'

WRITE_OFF_REASONS = frozenset({REASON_DAMAGE, REASON_EXPIRY, REASON_SPOILAGE})

REASON_TO_LOG_TYPE = {
    REASON_DAMAGE: 'damaged',
    REASON_EXPIRY: 'expired',
    REASON_SPOILAGE: 'spoiled',
}

ERR_INVALID_REASON = 'reason must be damage, expiry, or spoilage'
ERR_INVALID_QUANTITY = 'quantity must be greater than 0'
ERR_BATCH_REQUIRED = 'batch_id is required for batched products'
ERR_EXPIRY_NEEDS_BATCH = 'expiry write-off requires a batch'
ERR_NON_EXPIRED = 'Expiry write-off cannot target a non-expired batch'
ERR_INSUFFICIENT = 'quantity exceeds on-hand'
ERR_PRODUCT_NOT_FOUND = 'Product not found'
ERR_BATCH_NOT_FOUND = 'Batch not found'
ERR_PARENT_CHILD = 'Write off the parent bulk product'
ERR_NOT_TRACKED = 'Product does not track inventory'


class WriteOffError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def parse_write_off_quantity(raw):
    """Return a positive Decimal, or None when the value is not usable."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def parse_write_off_batch_id(raw):
    """Return int batch id, None when omitted, or False when unparseable."""
    if raw in (None, ''):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return False


def write_off_stock(
    *,
    product_id,
    retailer,
    quantity,
    reason,
    batch_id=None,
    created_by=None,
):
    """
    Lock the product (and batch), decrease on-hand, write an inventory log.

    ``quantity`` must already be a positive Decimal. ``reason`` is one of
    damage / expiry / spoilage. Expiry requires ``batch.is_expired()``.
    """
    if reason not in WRITE_OFF_REASONS:
        raise WriteOffError(ERR_INVALID_REASON, 400)
    if not isinstance(quantity, Decimal) or quantity <= 0:
        raise WriteOffError(ERR_INVALID_QUANTITY, 400)

    with transaction.atomic():
        try:
            product = Product.objects.select_for_update().get(
                id=product_id, retailer=retailer
            )
        except Product.DoesNotExist as exc:
            raise WriteOffError(ERR_PRODUCT_NOT_FOUND, 404) from exc

        if product.parent_bulk_product_id:
            raise WriteOffError(ERR_PARENT_CHILD, 400)
        if not product.track_inventory:
            raise WriteOffError(ERR_NOT_TRACKED, 400)

        batch = None
        if batch_id is not None:
            try:
                batch = ProductBatch.objects.select_for_update().get(
                    id=batch_id, product=product
                )
            except ProductBatch.DoesNotExist as exc:
                raise WriteOffError(ERR_BATCH_NOT_FOUND, 404) from exc
        elif product.has_batches:
            raise WriteOffError(ERR_BATCH_REQUIRED, 400)

        if reason == REASON_EXPIRY:
            if batch is None:
                raise WriteOffError(ERR_EXPIRY_NEEDS_BATCH, 400)
            if not batch.is_expired():
                raise WriteOffError(ERR_NON_EXPIRED, 400)

        if batch is not None:
            previous = batch.quantity
            if quantity > previous:
                raise WriteOffError(ERR_INSUFFICIENT, 400)
            batch.quantity = previous - quantity
            batch.save(update_fields=['quantity'])
            product.quantity = product.quantity - quantity
            product.save(update_fields=['quantity'])
            new_quantity = batch.quantity
        else:
            previous = product.quantity
            if quantity > previous:
                raise WriteOffError(ERR_INSUFFICIENT, 400)
            product.quantity = previous - quantity
            product.save(update_fields=['quantity'])
            new_quantity = product.quantity

        return ProductInventoryLog.objects.create(
            product=product,
            batch=batch,
            log_type=REASON_TO_LOG_TYPE[reason],
            quantity_change=quantity,
            previous_quantity=previous,
            new_quantity=new_quantity,
            reason=reason,
            created_by=created_by,
        )
