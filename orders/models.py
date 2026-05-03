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
        ('cash', 'Cash'),
        ('cash_pickup', 'Cash on Pickup'),
        ('upi', 'UPI'),
        ('online', 'Online App Payment'),
        ('card', 'Card'),
        ('credit', 'Credit (Udhaar)'),
        ('split', 'Split Payment'),
    ]
    
    CANCELLED_BY_CHOICES = [
        ('customer', 'Customer'),
        ('retailer', 'Retailer'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending_payment', 'Pending Payment'),
        ('pending_verification', 'Pending Verification'),
        ('verified', 'Verified'),
        ('failed', 'Failed'),
    ]
    
    ORDER_SOURCE_CHOICES = [
        ('app', 'Online App'),
        ('pos', 'POS (Walk-in)'),
    ]
    
    # Order identification
    order_number = models.CharField(max_length=20, unique=True, editable=False)
    source = models.CharField(max_length=50, choices=ORDER_SOURCE_CHOICES, default='app')
    
    # Relationships
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='orders',
        null=True,
        blank=True
    )
    guest_name = models.CharField(max_length=255, blank=True, null=True)
    guest_mobile = models.CharField(max_length=15, blank=True, null=True)
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
    
    # Timing
    preparation_time_minutes = models.IntegerField(null=True, blank=True)
    estimated_ready_time = models.DateTimeField(null=True, blank=True)
    expected_processing_start = models.DateTimeField(null=True, blank=True)
    
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
    
    # Payment Breakdown (for Split/POS)
    cash_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), null=True, blank=True)
    upi_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), null=True, blank=True)
    card_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), null=True, blank=True)
    credit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), null=True, blank=True)
    
    # Additional info
    special_instructions = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancelled_by = models.CharField(max_length=50, blank=True, null=True)
    payment_reference_id = models.CharField(max_length=100, blank=True, null=True)
    payment_status = models.CharField(max_length=50, choices=PAYMENT_STATUS_CHOICES, default='pending_payment')
    payment_edit_count = models.IntegerField(default=0)
    is_payment_locked = models.BooleanField(default=False)
    
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
        customer_name = self.customer.username if self.customer else (self.guest_name or "Walk-in")
        return f"Order #{self.order_number} - {customer_name}"
    
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
        """Thin compatibility façade that delegates status transitions to services."""
        from orders.services.status_service import update_order_status
        return update_order_status(self, new_status, user)

    def award_loyalty_points(self):
        """Awards loyalty points to the customer linked to this order"""
        if not self.customer:
            return False

        from decimal import Decimal
        from datetime import timedelta
        from django.utils import timezone
        from retailers.models import RetailerRewardConfig
        from customers.models import CustomerLoyalty, LoyaltyTransaction

        expiry_date = timezone.now() + timedelta(days=90)
        total_to_award = self.points_earned  # From specific offers if any

        try:
            config = RetailerRewardConfig.objects.filter(retailer=self.retailer).first()
            if not (config and config.is_active):
                return False

            # 0. Calculate Rule-Based Points (Separated from Offers)
            if self.subtotal >= config.loyalty_min_order_value:
                if config.earning_type == 'percentage':
                    rule_points = (self.subtotal * config.loyalty_earning_value) / Decimal('100.00')
                    total_to_award += rule_points
                elif config.earning_type == 'points_per_amount' and config.loyalty_earning_value > 0:
                    rule_points = self.subtotal // config.loyalty_earning_value
                    total_to_award += Decimal(str(rule_points))

            # 1. Award Total Points (Rule Points + Offer Points)
            if total_to_award > 0:
                loyalty, _ = CustomerLoyalty.objects.get_or_create(
                    customer=self.customer,
                    retailer=self.retailer
                )
                loyalty.points += total_to_award
                loyalty.save()
                
                # Update order to reflect actual points earned
                self.points_earned = total_to_award
                self.save(update_fields=['points_earned'])

                # Create Transaction
                LoyaltyTransaction.objects.create(
                    customer=self.customer,
                    retailer=self.retailer,
                    amount=total_to_award,
                    transaction_type='earn',
                    description=f"Earned from order #{self.order_number}",
                    expiry_date=expiry_date
                )

            # 2. Process Referral Reward
            if config.is_referral_enabled:
                from customers.models import CustomerReferral
                referral = CustomerReferral.objects.filter(
                    retailer=self.retailer,
                    referee=self.customer,
                    is_rewarded=False
                ).first()
                
                if referral and self.total_amount >= config.min_referral_order_amount:
                    # Reward Referrer
                    referrer_loyalty, _ = CustomerLoyalty.objects.get_or_create(
                        customer=referral.referrer,
                        retailer=self.retailer
                    )
                    referrer_loyalty.points += config.referral_reward_points
                    referrer_loyalty.save()
                    
                    # Log referer earned transaction
                    LoyaltyTransaction.objects.create(
                        customer=referral.referrer,
                        retailer=self.retailer,
                        amount=config.referral_reward_points,
                        transaction_type='earn',
                        description=f"Referral reward (for referee {self.customer.username})",
                        expiry_date=expiry_date
                    )

                    # Reward Referee
                    referee_loyalty, _ = CustomerLoyalty.objects.get_or_create(
                        customer=self.customer,
                        retailer=self.retailer
                    )
                    referee_loyalty.points += config.referee_reward_points
                    referee_loyalty.save()
                    
                    # Log referee earned transaction
                    LoyaltyTransaction.objects.create(
                        customer=self.customer,
                        retailer=self.retailer,
                        amount=config.referee_reward_points,
                        transaction_type='earn',
                        description=f"Referral reward (referred by {referral.referrer.username})",
                        expiry_date=expiry_date
                    )

                    # Mark referral as rewarded
                    referral.is_rewarded = True
                    referral.save()
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error awarding points: {e}")
            return False


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
    batch = models.ForeignKey(
        'products.ProductBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    # Product details at time of order
    product_name = models.CharField(max_length=255)
    product_price = models.DecimalField(max_digits=10, decimal_places=2)
    product_unit = models.CharField(max_length=20)
    
    # Order item details
    quantity = models.DecimalField(
        max_digits=12, 
        decimal_places=3, 
        validators=[MinValueValidator(Decimal('0.001'))]
    )
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
        # normalize() strips trailing zeros: 2.000 -> 2, 1.500 -> 1.5
        qty_display = self.quantity.normalize()
        return f"{self.product_name} x {qty_display}"
    
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


class OrderChatMessage(models.Model):
    """
    Chat messages between customer and retailer for an order
    """
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='chat_messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL,
        null=True
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'order_chat_message'
        indexes = [
            models.Index(fields=['order', 'created_at']),
        ]
        ordering = ['created_at']
    
    def __str__(self):
        return f"Chat on {self.order.order_number}: {self.message[:20]}"


class RetailerRating(models.Model):
    """
    Rating given by retailer to a customer
    """
    order = models.OneToOneField(
        Order, 
        on_delete=models.CASCADE, 
        related_name='retailer_rating'
    )
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
    )
    rating = models.PositiveIntegerField() # 0-5 stars
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'retailer_rating'
        unique_together = ['order', 'retailer'] # One rating per order
    
    def __str__(self):
        return f"Rating for {self.customer.username} by {self.retailer.shop_name}: {self.rating}"


# Signals for Rating Updates

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Avg

@receiver(post_save, sender=OrderFeedback)
def update_retailer_rating_stats(sender, instance, created, **kwargs):
    """
    Update retailer's average rating when a new feedback is added
    """
    if created:
        from orders.services.rating_service import sync_retailer_feedback_stats
        sync_retailer_feedback_stats(instance.order.retailer)


@receiver(post_save, sender=RetailerRating)
def update_customer_rating_stats(sender, instance, created, **kwargs):
    """
    Update customer's average rating and handle blacklist
    """
    if created or instance.rating >= 0:
        from orders.services.rating_service import apply_retailer_rating_effects
        apply_retailer_rating_effects(instance)
