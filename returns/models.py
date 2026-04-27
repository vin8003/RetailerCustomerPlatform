from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal

class SalesReturn(models.Model):
    """
    Records of items returned by customers (POS or App)
    """
    PAYMENT_MODE_CHOICES = [
        ('cash', 'Cash'),
        ('upi', 'UPI'),
    ]

    retailer = models.ForeignKey(
        'retailers.RetailerProfile',
        on_delete=models.CASCADE,
        related_name='sales_returns'
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='returns'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_returns'
    )
    
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refund_payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    reason = models.TextField(blank=True)
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processed_sales_returns'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sales_return'
        ordering = ['-created_at']

    def __str__(self):
        return f"Return for Order {self.order.order_number if self.order else self.id}"


class SalesReturnItem(models.Model):
    """
    Line items for a sales return
    """
    sales_return = models.ForeignKey(
        SalesReturn,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE
    )
    batch = models.ForeignKey(
        'products.ProductBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    order_item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='returns'
    )
    quantity = models.PositiveIntegerField()
    refund_unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_refund = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'sales_return_item'

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (Return)"


class PurchaseReturn(models.Model):
    """
    Records of items returned to suppliers
    """
    retailer = models.ForeignKey(
        'retailers.RetailerProfile',
        on_delete=models.CASCADE,
        related_name='purchase_returns'
    )
    supplier = models.ForeignKey(
        'retailers.Supplier',
        on_delete=models.CASCADE,
        related_name='purchase_returns'
    )
    invoice = models.ForeignKey(
        'products.PurchaseInvoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='returns'
    )
    
    return_number = models.CharField(max_length=100, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    
    return_date = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processed_purchase_returns'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchase_return'
        ordering = ['-created_at']

    def __str__(self):
        return f"Return to {self.supplier.company_name} - {self.total_amount}"


class PurchaseReturnItem(models.Model):
    """
    Line items for a purchase return
    """
    purchase_return = models.ForeignKey(
        PurchaseReturn,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE
    )
    batch = models.ForeignKey(
        'products.ProductBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    purchase_item = models.ForeignKey(
        'products.PurchaseItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='returns'
    )
    quantity = models.PositiveIntegerField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'purchase_return_item'

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (Purchase Return)"
