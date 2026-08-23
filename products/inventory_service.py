"""
Centralized inventory helpers for KAN-75: keep product.quantity and batches in sync,
log product-level balances, and replay ledger movements for data repair.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from products.models import Product, ProductBatch, ProductInventoryLog


def _signed_delta(log_type: str, quantity_change: Decimal) -> Decimal:
    change = Decimal(str(quantity_change))
    if log_type in ('added', 'returned'):
        return abs(change)
    if log_type in ('removed', 'damaged', 'expired'):
        return -abs(change)
    if log_type == 'sold':
        return change if change < 0 else -abs(change)
    return change


def replay_quantity_from_logs(product: Product) -> Decimal:
    """
    Reconstruct product quantity by replaying inventory log movements.
    Uses quantity_change (signed by log_type), not new_quantity when batch_id is set.
    """
    logs = list(
        ProductInventoryLog.objects.filter(product=product).order_by('created_at', 'id')
    )
    if not logs:
        return Decimal(str(product.quantity))

    running = Decimal(str(logs[0].previous_quantity))
    for log in logs:
        running += _signed_delta(log.log_type, log.quantity_change)
    return running


def sync_initial_stock_batch(product: Product) -> None:
    """Keep INITIAL-STOCK aligned with product.quantity for non-multi-batch products."""
    if product.has_batches:
        return
    batch = (
        product.batches.filter(batch_number='INITIAL-STOCK').first()
        or product.batches.filter(is_active=True).first()
    )
    if batch:
        batch.quantity = product.quantity
        batch.save(update_fields=['quantity'])


def consolidate_stock_to_initial_batch(product: Product) -> None:
    """
    After link_barcode creates an empty secondary batch, move all stock onto
    INITIAL-STOCK so product.quantity is not lost across batches.
    """
    if not product.has_batches:
        return
    initial = product.batches.filter(batch_number='INITIAL-STOCK', is_active=True).first()
    if not initial:
        return
    other_sum = (
        product.batches.filter(is_active=True)
        .exclude(pk=initial.pk)
        .aggregate(total=Sum('quantity'))['total']
        or Decimal('0')
    )
    initial.quantity = Decimal(str(product.quantity)) - Decimal(str(other_sum))
    initial.save(update_fields=['quantity'])
    product.sync_inventory_from_batches()


def apply_stock_increase(product: Product, quantity, batch=None, *, allow_negative: bool = False) -> Decimal:
    """Increase stock via model helpers; returns new product.quantity."""
    qty = Decimal(str(quantity))
    if not product.increase_quantity(qty, batch=batch):
        raise ValueError(f'Failed to increase stock for product {product.pk}')
    if not product.has_batches:
        sync_initial_stock_batch(product)
    product.refresh_from_db()
    return product.quantity


def apply_stock_decrease(product: Product, quantity, batch=None, *, allow_negative: bool = False) -> Decimal:
    """Decrease stock via model helpers; returns new product.quantity."""
    qty = Decimal(str(quantity))
    if not product.reduce_quantity(qty, batch=batch, allow_negative=allow_negative):
        raise ValueError(f'Failed to decrease stock for product {product.pk}')
    if not product.has_batches:
        sync_initial_stock_batch(product)
    product.refresh_from_db()
    return product.quantity


def log_inventory_change(
    *,
    product: Product,
    log_type: str,
    quantity_change: Decimal,
    previous_quantity: Decimal,
    new_quantity: Decimal,
    reason: str,
    created_by=None,
    batch=None,
) -> ProductInventoryLog:
    """Always log product-level previous/new balances (batch_id is audit-only)."""
    return ProductInventoryLog.objects.create(
        product=product,
        batch=batch,
        log_type=log_type,
        quantity_change=quantity_change,
        previous_quantity=previous_quantity,
        new_quantity=new_quantity,
        reason=reason,
        created_by=created_by,
    )


@transaction.atomic
def reconcile_product_from_logs(
    product: Product,
    *,
    dry_run: bool = True,
    created_by=None,
    reason: str = 'KAN-75 stock reconstruction from inventory logs',
) -> dict:
    """
    Replay logs to compute correct qty, put stock on INITIAL-STOCK, deactivate
    phantom empty barcode batches. dry_run=True reports only (safe for prod review).
    """
    product = Product.objects.select_for_update().get(pk=product.pk)
    current_qty = Decimal(str(product.quantity))
    replayed_qty = replay_quantity_from_logs(product)

    initial = product.batches.filter(batch_number='INITIAL-STOCK').first()
    phantom_batches = list(
        product.batches.filter(is_active=True)
        .exclude(batch_number='INITIAL-STOCK')
        .filter(quantity__lte=0)
    )

    result = {
        'product_id': product.id,
        'product_name': product.name,
        'current_quantity': current_qty,
        'replayed_quantity': replayed_qty,
        'delta': replayed_qty - current_qty,
        'dry_run': dry_run,
        'phantom_batch_ids': [b.id for b in phantom_batches],
    }

    if dry_run:
        return result

    prev_qty = current_qty
    product.quantity = replayed_qty
    product.save(update_fields=['quantity'])

    if initial:
        initial.quantity = replayed_qty
        initial.is_active = True
        initial.save(update_fields=['quantity', 'is_active'])
    else:
        ProductBatch.objects.create(
            product=product,
            retailer=product.retailer,
            batch_number='INITIAL-STOCK',
            barcode=product.barcode,
            price=product.price,
            original_price=product.original_price,
            purchase_price=product.purchase_price or product.price,
            quantity=replayed_qty,
            is_active=True,
        )

    for batch in phantom_batches:
        batch.quantity = Decimal('0')
        batch.is_active = False
        batch.save(update_fields=['quantity', 'is_active'])

    if product.has_batches:
        # Keep remaining real batches; put leftover reconstructed qty on INITIAL-STOCK
        # so sync_inventory_from_batches cannot overwrite the replayed total.
        remaining_other = (
            product.batches.filter(is_active=True)
            .exclude(batch_number='INITIAL-STOCK')
            .aggregate(total=Sum('quantity'))['total']
            or Decimal('0')
        )
        initial = product.batches.filter(batch_number='INITIAL-STOCK').first()
        if initial:
            initial.quantity = replayed_qty - Decimal(str(remaining_other))
            initial.save(update_fields=['quantity'])
        product.sync_inventory_from_batches()

    log_inventory_change(
        product=product,
        log_type='added' if replayed_qty >= prev_qty else 'removed',
        quantity_change=abs(replayed_qty - prev_qty),
        previous_quantity=prev_qty,
        new_quantity=replayed_qty,
        reason=reason,
        created_by=created_by,
    )

    product.refresh_from_db()
    result['applied_quantity'] = product.quantity
    return result
