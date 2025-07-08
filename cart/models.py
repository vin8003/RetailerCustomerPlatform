from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal


class Cart(models.Model):
    """
    Shopping cart for customers
    """
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='carts'
    )
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='customer_carts'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'cart'
        unique_together = ['customer', 'retailer']
        indexes = [
            models.Index(fields=['customer', 'retailer']),
            models.Index(fields=['updated_at']),
        ]
    
    def __str__(self):
        return f"Cart - {self.customer.username} - {self.retailer.shop_name}"
    
    @property
    def total_items(self):
        """Get total number of items in cart"""
        return self.items.aggregate(total=models.Sum('quantity'))['total'] or 0
    
    @property
    def total_amount(self):
        """Calculate total amount of cart"""
        return sum(item.total_price for item in self.items.all())
    
    @property
    def is_empty(self):
        """Check if cart is empty"""
        return not self.items.exists()
    
    def clear(self):
        """Clear all items from cart"""
        self.items.all().delete()
        self.save()
    
    def add_item(self, product, quantity=1):
        """Add item to cart or update quantity if exists"""
        try:
            cart_item = self.items.get(product=product)
            cart_item.quantity += quantity
            cart_item.save()
            return cart_item
        except CartItem.DoesNotExist:
            cart_item = CartItem.objects.create(
                cart=self,
                product=product,
                quantity=quantity,
                unit_price=product.price
            )
            return cart_item
    
    def remove_item(self, product):
        """Remove item from cart"""
        try:
            cart_item = self.items.get(product=product)
            cart_item.delete()
            return True
        except CartItem.DoesNotExist:
            return False
    
    def update_item_quantity(self, product, quantity):
        """Update quantity of specific item"""
        try:
            cart_item = self.items.get(product=product)
            if quantity <= 0:
                cart_item.delete()
            else:
                cart_item.quantity = quantity
                cart_item.save()
            return True
        except CartItem.DoesNotExist:
            return False


class CartItem(models.Model):
    """
    Individual items in a shopping cart
    """
    cart = models.ForeignKey(
        Cart, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    product = models.ForeignKey(
        'products.Product', 
        on_delete=models.CASCADE
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)]
    )
    unit_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'cart_item'
        unique_together = ['cart', 'product']
        indexes = [
            models.Index(fields=['cart', 'added_at']),
            models.Index(fields=['product']),
        ]
    
    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
    
    @property
    def total_price(self):
        """Calculate total price for this item"""
        return self.unit_price * self.quantity
    
    @property
    def is_available(self):
        """Check if product is available in requested quantity"""
        return self.product.can_order_quantity(self.quantity)
    
    def save(self, *args, **kwargs):
        """Override save to update unit price from product"""
        if not self.unit_price:
            self.unit_price = self.product.price
        super().save(*args, **kwargs)
        
        # Update cart's updated_at timestamp
        self.cart.save()


class CartSession(models.Model):
    """
    Session-based cart for anonymous users (future enhancement)
    """
    session_key = models.CharField(max_length=40, unique=True)
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE
    )
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'cart_session'
        indexes = [
            models.Index(fields=['session_key']),
            models.Index(fields=['updated_at']),
        ]
    
    def __str__(self):
        return f"Session Cart - {self.session_key}"


class CartHistory(models.Model):
    """
    History of cart operations for analytics
    """
    ACTION_CHOICES = [
        ('add', 'Add Item'),
        ('remove', 'Remove Item'),
        ('update', 'Update Quantity'),
        ('clear', 'Clear Cart'),
        ('checkout', 'Checkout'),
    ]
    
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='cart_history'
    )
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        'products.Product', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'cart_history'
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['retailer', 'created_at']),
            models.Index(fields=['action']),
        ]
    
    def __str__(self):
        return f"{self.customer.username} - {self.action} - {self.created_at}"
