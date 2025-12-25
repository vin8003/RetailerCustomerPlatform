from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid


class Order(models.Model):
    """
    Order model for customer orders
    """
    ORDER_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('waiting_for_customer_approval', 'Waiting for Customer Approval'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('packed', 'Packed'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('returned', 'Returned'),
    ]
    
    DELIVERY_MODE_CHOICES = [
        ('delivery', 'Delivery'),
        ('pickup', 'Pickup'),
    ]
    
    PAYMENT_MODE_CHOICES = [
        ('cash', 'Cash on Delivery'),
        ('cash_pickup', 'Cash on Pickup'),
    ]
    
    # Order identification
    order_number = models.CharField(max_length=20, unique=True, editable=False)
    
    # Relationships
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='orders'
    )
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='orders'
    )
    delivery_address = models.ForeignKey(
        'customers.CustomerAddress', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    
    # Order details
    delivery_mode = models.CharField(max_length=20, choices=DELIVERY_MODE_CHOICES)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    status = models.CharField(max_length=50, choices=ORDER_STATUS_CHOICES, default='pending')
    
    # Pricing
    subtotal = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    delivery_fee = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    discount_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    discount_from_points = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    points_earned = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0
    )
    points_redeemed = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0
    )
    total_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    
    # Additional info
    special_instructions = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'order'
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['retailer', 'status']),
            models.Index(fields=['order_number']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Order #{self.order_number} - {self.customer.username}"
    
    def save(self, *args, **kwargs):
        """Generate order number if not exists"""
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)
    
    def generate_order_number(self):
        """Generate unique order number"""
        import time
        import random
        
        # Format: ORD-YYYYMMDD-HHMMSS-RRR
        timestamp = int(time.time())
        random_part = random.randint(100, 999)
        order_number = f"ORD-{timestamp}-{random_part}"
        
        # Ensure uniqueness
        while Order.objects.filter(order_number=order_number).exists():
            random_part = random.randint(100, 999)
            order_number = f"ORD-{timestamp}-{random_part}"
        
        return order_number
    
    @property
    def can_be_cancelled(self):
        """Check if order can be cancelled"""
        return self.status in ['pending', 'confirmed', 'processing']
    
    @property
    def is_completed(self):
        """Check if order is completed"""
        return self.status in ['delivered', 'cancelled', 'returned']
    
    def update_status(self, new_status, user=None):
        """Update order status with timestamp"""
        from django.utils import timezone
        
        old_status = self.status
        self.status = new_status
        
        # Set status-specific timestamps
        if new_status == 'confirmed':
            self.confirmed_at = timezone.now()
        elif new_status == 'delivered':
            self.delivered_at = timezone.now()
            
            # Award cashback points
            # Award cashback points
            if old_status != 'delivered':
                from decimal import Decimal
                from retailers.models import RetailerRewardConfig
                from customers.models import CustomerLoyalty
                
                try:
                    config = RetailerRewardConfig.objects.filter(retailer=self.retailer).first()
                    if config and config.is_active:
                        # Calculate points
                        points_to_earn = (self.total_amount * config.cashback_percentage) / Decimal('100.0')
                        points_to_earn = round(points_to_earn, 2)
                        
                        if points_to_earn > 0:
                            self.points_earned = points_to_earn
                            
                            # Update Customer Loyalty for this retailer
                            loyalty, _ = CustomerLoyalty.objects.get_or_create(
                                customer=self.customer,
                                retailer=self.retailer
                            )
                            loyalty.points += points_to_earn
                            loyalty.save()
                        
                except Exception as e:
                    print(f"Error awarding points: {e}")
                    
        elif new_status == 'cancelled':
            self.cancelled_at = timezone.now()
            
            # Refund points if order used any
            if old_status != 'cancelled' and self.points_redeemed > 0:
                from customers.models import CustomerLoyalty
                try:
                    loyalty, _ = CustomerLoyalty.objects.get_or_create(
                        customer=self.customer,
                        retailer=self.retailer
                    )
                    loyalty.points += self.points_redeemed
                    loyalty.save()
                except Exception as e:
                    print(f"Error refunding points: {e}")
                
            # Revert earned points if accidentally marked delivered then cancelled
            if self.points_earned > 0:
                from customers.models import CustomerLoyalty
                try:
                    loyalty, _ = CustomerLoyalty.objects.get_or_create(
                        customer=self.customer,
                        retailer=self.retailer
                    )
                    loyalty.points -= self.points_earned
                    if loyalty.points < 0:
                        loyalty.points = 0
                    loyalty.save()
                    self.points_earned = 0
                except Exception as e:
                     print(f"Error reverting points: {e}")
        
        self.save()
        
        # Create status log
        OrderStatusLog.objects.create(
            order=self,
            old_status=old_status,
            new_status=new_status,
            changed_by=user
        )
        
        # Create notification for customer
        from customers.models import CustomerNotification
        
        status_messages = {
            'confirmed': 'Your order has been confirmed',
            'processing': 'Your order is being processed',
            'packed': 'Your order has been packed',
            'out_for_delivery': 'Your order is out for delivery',
            'delivered': 'Your order has been delivered',
            'cancelled': 'Your order has been cancelled',
            'returned': 'Your order has been returned',
            'waiting_for_customer_approval': 'Order modifications require your approval'
        }
        
        if new_status in status_messages:
            msg = status_messages[new_status]
            CustomerNotification.objects.create(
                customer=self.customer,
                notification_type='order_update',
                title=f'Order #{self.order_number} Update',
                message=msg
            )
            
            # Send Push Notification
            from common.notifications import send_push_notification, send_silent_update
            send_push_notification(
                user=self.customer,
                title=f"Order Update: #{self.order_number}",
                message=msg,
                data={
                    'type': 'order_status_update',
                    'order_id': str(self.id),
                    'status': new_status
                }
            )
            
            # Send silent update to refresh UI
            send_silent_update(
                user=self.customer,
                event_type='order_refresh',
                data={'order_id': str(self.id)}
            )
            
            # Also notify and refresh Retailer UI
            send_silent_update(
                user=self.retailer.user,
                event_type='order_refresh',
                data={'order_id': str(self.id)}
            )
            
            # If customer updated the status (accepted/rejected), 
            # send a visible push to the retailer
            if user == self.customer:
                action_text = "accepted" if new_status == 'confirmed' else "rejected"
                send_push_notification(
                    user=self.retailer.user,
                    title=f"Order Update: #{self.order_number}",
                    message=f"Customer has {action_text} the order modifications.",
                    data={
                        'type': 'order_status_update',
                        'order_id': str(self.id),
                        'status': new_status
                    }
                )


class OrderItem(models.Model):
    """
    Order items for individual products in an order
    """
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    product = models.ForeignKey(
        'products.Product', 
        on_delete=models.CASCADE
    )
    
    # Product details at time of order
    product_name = models.CharField(max_length=255)
    product_price = models.DecimalField(max_digits=10, decimal_places=2)
    product_unit = models.CharField(max_length=20)
    
    # Order item details
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'order_item'
        indexes = [
            models.Index(fields=['order']),
            models.Index(fields=['product']),
        ]
    
    def __str__(self):
        return f"{self.product_name} x {self.quantity}"
    
    def save(self, *args, **kwargs):
        """Calculate total price"""
        self.total_price = self.unit_price * self.quantity
        super().save(*args, **kwargs)


class OrderStatusLog(models.Model):
    """
    Log for order status changes
    """
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='status_logs'
    )
    old_status = models.CharField(max_length=50)
    new_status = models.CharField(max_length=50)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'order_status_log'
        indexes = [
            models.Index(fields=['order', 'created_at']),
        ]
    
    def __str__(self):
        return f"Order #{self.order.order_number} - {self.old_status} → {self.new_status}"


class OrderDelivery(models.Model):
    """
    Delivery information for orders
    """
    DELIVERY_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('assigned', 'Assigned'),
        ('picked_up', 'Picked Up'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ]
    
    order = models.OneToOneField(
        Order, 
        on_delete=models.CASCADE, 
        related_name='delivery_info'
    )
    
    # Delivery details
    delivery_person_name = models.CharField(max_length=255, blank=True)
    delivery_person_phone = models.CharField(max_length=15, blank=True)
    estimated_delivery_time = models.DateTimeField(null=True, blank=True)
    actual_delivery_time = models.DateTimeField(null=True, blank=True)
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default='pending')
    
    # Tracking
    tracking_id = models.CharField(max_length=50, blank=True)
    delivery_notes = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'order_delivery'
    
    def __str__(self):
        return f"Delivery for Order #{self.order.order_number}"


class OrderFeedback(models.Model):
    """
    Customer feedback for orders
    """
    order = models.OneToOneField(
        Order, 
        on_delete=models.CASCADE, 
        related_name='feedback'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
    )
    
    # Ratings (1-5 stars)
    overall_rating = models.PositiveIntegerField()
    product_quality_rating = models.PositiveIntegerField()
    delivery_rating = models.PositiveIntegerField()
    service_rating = models.PositiveIntegerField()
    
    # Comments
    comment = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'order_feedback'
    
    def __str__(self):
        return f"Feedback for Order #{self.order.order_number}"


class OrderReturn(models.Model):
    """
    Order return requests
    """
    RETURN_STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
    ]
    
    RETURN_REASON_CHOICES = [
        ('defective', 'Defective Product'),
        ('wrong_item', 'Wrong Item'),
        ('damaged', 'Damaged'),
        ('not_satisfied', 'Not Satisfied'),
        ('other', 'Other'),
    ]
    
    order = models.OneToOneField(
        Order, 
        on_delete=models.CASCADE, 
        related_name='return_request'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
    )
    
    # Return details
    reason = models.CharField(max_length=20, choices=RETURN_REASON_CHOICES)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=RETURN_STATUS_CHOICES, default='requested')
    
    # Admin response
    admin_notes = models.TextField(blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='processed_returns'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'order_return'
    
    def __str__(self):
        return f"Return request for Order #{self.order.order_number}"
