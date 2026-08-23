"""
Centralized inventory helpers for KAN-75: keep product.quantity and batches in sync,
log product-level balances, and replay ledger movements for data repair.

Replay invariant
----------------
`replay_quantity_from_logs` reconstructs stock from *movements* (`quantity_change`
signed by `log_type`), not from `new_quantity` (which may be batch-level on
legacy rows). Opening balance is the first product-level log's
`previous_quantity` (batch_id is NULL). If every movement log is batch-level,
the first `previous_quantity` is used anyway and `base_trusted` is False.

`reconciled` logs are audit-only (delta 0) so `--apply` is idempotent.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from products.models import Product, ProductBatch, ProductInventoryLog

logger = logging.getLogger(__name__)

RECONCILED_LOG_TYPE = 'reconciled'


def _signed_delta(log_type: str, quantity_change: Decimal) -> Decimal:
    change = Decimal(str(quantity_change))
    if log_type == RECONCILED_LOG_TYPE:
        return Decimal('0')
    if log_type in ('added', 'returned'):
        return abs(change)
    if log_type in ('removed', 'damaged', 'expired'):
        return -abs(change)
    if log_type == 'sold':
        if change > 0:
            logger.warning(
                'sold inventory log has positive quantity_change=%s; treating as a decrease',
                change,
            )
            return -abs(change)
        return change
    return change


def replay_inventory_state(product: Product) -> dict:
    """
    Reconstruct product quantity from inventory logs.

    Returns quantity plus whether the opening balance is trusted product-level
    stock (`base_trusted`) and an optional operator warning.
    """
    logs = list(
        ProductInventoryLog.objects.filter(product=product).order_by('created_at', 'id')
    )
    movement_logs = [log for log in logs if log.log_type != RECONCILED_LOG_TYPE]
    if not movement_logs:
        return {
            'quantity': Decimal(str(product.quantity)),
            'base_trusted': True,
            'warning': None,
        }

    product_level = [log for log in movement_logs if log.batch_id is None]
    if product_level:
        anchor = product_level[0]
        running = Decimal(str(anchor.previous_quantity))
        applying = False
        for log in movement_logs:
            if log.pk == anchor.pk:
                applying = True
            if applying:
                running += _signed_delta(log.log_type, log.quantity_change)
        warning = None
        if movement_logs[0].batch_id is not None:
            warning = (
                'Earliest log is batch-level; replay anchored at first '
                'product-level previous_quantity (earlier batch-level '
                'balances ignored).'
            )
        return {
            'quantity': running,
            'base_trusted': True,
            'warning': warning,
        }

    running = Decimal(str(movement_logs[0].previous_quantity))
    for log in movement_logs:
        running += _signed_delta(log.log_type, log.quantity_change)
    return {
        'quantity': running,
        'base_trusted': False,
        'warning': (
            'All movement logs are batch-level; opening previous_quantity '
            'may be batch stock, not product stock. Review before --apply.'
        ),
    }


def replay_quantity_from_logs(product: Product) -> Decimal:
    """Reconstruct product quantity by replaying inventory log movements."""
    return replay_inventory_state(product)['quantity']


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


def apply_stock_increase(product: Product, quantity, batch=None) -> Decimal:
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


def _barcode_for_initial_stock(product: Product) -> str:
    barcode = product.barcode or None
    if barcode and product.batches.exclude(batch_number='INITIAL-STOCK').filter(barcode=barcode).exists():
        return None
    return barcode


def _ensure_initial_stock_batch(product: Product, quantity: Decimal) -> ProductBatch:
    barcode = _barcode_for_initial_stock(product)
    initial = product.batches.filter(batch_number='INITIAL-STOCK').first()
    if initial:
        initial.quantity = quantity
        initial.is_active = True
        initial.save(update_fields=['quantity', 'is_active'])
        return initial
    return ProductBatch.objects.create(
        product=product,
        retailer=product.retailer,
        batch_number='INITIAL-STOCK',
        barcode=barcode,
        price=product.price,
        original_price=product.original_price,
        purchase_price=product.purchase_price or product.price,
        quantity=quantity,
        is_active=True,
    )


def reconcile_product_from_logs(
    product: Product,
    *,
    dry_run: bool = True,
    created_by=None,
    reason: str = 'KAN-75 stock reconstruction from inventory logs',
) -> dict:
    """
    Replay logs to compute correct qty, put stock on INITIAL-STOCK, deactivate
    phantom empty barcode batches. dry_run=True reports only and does not
    acquire row locks.
    """
    if dry_run:
        product = Product.objects.get(pk=product.pk)
        return _reconcile_result(product, dry_run=True)

    with transaction.atomic():
        product = Product.objects.select_for_update().get(pk=product.pk)
        result = _reconcile_result(product, dry_run=False)
        if result['delta'] == 0 and not result['phantom_batch_ids'] and product.batches.filter(batch_number='INITIAL-STOCK').exists():
            result['applied_quantity'] = result['current_quantity']
            return result

        prev_qty = result['current_quantity']
        replayed_qty = result['replayed_quantity']
        product.quantity = replayed_qty
        product.save(update_fields=['quantity'])

        initial = _ensure_initial_stock_batch(product, replayed_qty)

        for batch in product.batches.filter(is_active=True).exclude(batch_number='INITIAL-STOCK').filter(quantity__lte=0):
            batch.quantity = Decimal('0')
            batch.is_active = False
            batch.save(update_fields=['quantity', 'is_active'])

        if product.has_batches:
            remaining_other = (
                product.batches.filter(is_active=True)
                .exclude(batch_number='INITIAL-STOCK')
                .aggregate(total=Sum('quantity'))['total']
                or Decimal('0')
            )
            initial.quantity = replayed_qty - Decimal(str(remaining_other))
            initial.save(update_fields=['quantity'])
            product.sync_inventory_from_batches()

        if result['delta'] != 0:
            log_inventory_change(
                product=product,
                log_type=RECONCILED_LOG_TYPE,
                quantity_change=abs(replayed_qty - prev_qty),
                previous_quantity=prev_qty,
                new_quantity=replayed_qty,
                reason=reason,
                created_by=created_by,
            )

        product.refresh_from_db()
        result['applied_quantity'] = product.quantity
        return result


def _reconcile_result(product: Product, *, dry_run: bool) -> dict:
    current_qty = Decimal(str(product.quantity))
    state = replay_inventory_state(product)
    replayed_qty = state['quantity']
    phantom_batches = list(
        product.batches.filter(is_active=True)
        .exclude(batch_number='INITIAL-STOCK')
        .filter(quantity__lte=0)
    )
    return {
        'product_id': product.id,
        'product_name': product.name,
        'current_quantity': current_qty,
        'replayed_quantity': replayed_qty,
        'delta': replayed_qty - current_qty,
        'dry_run': dry_run,
        'phantom_batch_ids': [b.id for b in phantom_batches],
        'base_trusted': state['base_trusted'],
        'warning': state['warning'],
    }
