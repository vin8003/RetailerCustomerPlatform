"""Shared order inventory helpers (ATP restore on cancel/reject)."""


def restore_order_inventory(order, user, *, reason=None):
    """
    Return reserved stock to product ATP when an order is cancelled/rejected.

    Mirrors cancel_order view behaviour so inbox and direct cancel stay aligned.
    """
    reason = reason or f"Order Cancelled: #{order.order_number}"
    logs_to_create = []
    prefetched_items = getattr(order, '_prefetched_objects_cache', {}).get('items')
    if prefetched_items is not None:
        items = prefetched_items
    else:
        items = order.items.select_related('product').all()
    for item in items:
        product = item.product
        if product is None:
            continue
        prev_qty = product.quantity
        product.increase_quantity(item.quantity)
        new_qty = prev_qty + item.quantity

        from products.models import ProductInventoryLog

        logs_to_create.append(
            ProductInventoryLog(
                product=product,
                log_type='returned',
                quantity_change=item.quantity,
                previous_quantity=prev_qty,
                new_quantity=new_qty,
                reason=reason,
                created_by=user,
            )
        )

    if logs_to_create:
        from products.models import ProductInventoryLog

        ProductInventoryLog.objects.bulk_create(logs_to_create)
