from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from .models import ProductCategory
from .search_cache import bump_search_cache

@receiver(post_save, sender=ProductCategory)
@receiver(post_delete, sender=ProductCategory)
def invalidate_category_tree_cache(sender, instance, **kwargs):
    """
    Invalidate the category tree cache whenever a category is created, updated, or deleted.
    """
    cache_key = 'category_tree_structure'
    cache.delete(cache_key)
    # Also invalidate any derived caches if we add them later

from django.db.models import Sum
from decimal import Decimal

@receiver(post_save, sender='products.SupplierLedger')
@receiver(post_delete, sender='products.SupplierLedger')
def sync_supplier_ledger_balances(sender, instance, **kwargs):
    """
    Syncs the supplier balance_due and automatically allocates payments to the oldest invoices
    (Waterfall Allocation).
    """
    supplier = getattr(instance, 'supplier', None)
    if not supplier:
        return

    from products.models import SupplierLedger, PurchaseInvoice
    from retailers.models import Supplier

    credits_sum = SupplierLedger.objects.filter(supplier=supplier, transaction_type='CREDIT').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    debits_sum = SupplierLedger.objects.filter(supplier=supplier, transaction_type='DEBIT').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    new_balance = credits_sum - debits_sum
    Supplier.objects.filter(id=supplier.id).update(balance_due=new_balance)
    
    # FIFO Allocation Waterfall
    invoices = PurchaseInvoice.objects.filter(supplier=supplier).order_by('invoice_date', 'created_at')
    remaining_pool = debits_sum
    
    for invoice in invoices:
        total_req = invoice.total_amount
        if remaining_pool >= total_req:
            allocated = total_req
            remaining_pool -= total_req
            status = 'PAID'
        elif remaining_pool > 0:
            allocated = remaining_pool
            remaining_pool = Decimal('0.00')
            status = 'PARTIAL'
        else:
            allocated = Decimal('0.00')
            status = 'UNPAID'
            
        if invoice.paid_amount != allocated or invoice.payment_status != status:
            PurchaseInvoice.objects.filter(id=invoice.id).update(
                paid_amount=allocated,
                payment_status=status
            )


from .models import Product, ProductBatch


@receiver(post_save, sender=Product)
@receiver(post_delete, sender=Product)
def bump_search_cache_on_product_change(sender, instance, **kwargs):
    """Every sale, restock, price edit or delete goes through a Product save, so searches never show stale stock."""
    bump_search_cache(instance.retailer_id)


@receiver(post_save, sender=ProductBatch)
@receiver(post_delete, sender=ProductBatch)
def bump_search_cache_on_batch_change(sender, instance, **kwargs):
    retailer_id = instance.retailer_id
    if retailer_id is None:
        retailer_id = (
            Product.objects.filter(pk=instance.product_id)
            .values_list('retailer_id', flat=True)
            .first()
        )
    bump_search_cache(retailer_id)
