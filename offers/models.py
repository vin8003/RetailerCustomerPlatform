from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from django.utils import timezone

class Offer(models.Model):
    """
    Configuration for an offer/promotion
    """
    OFFER_TYPE_CHOICES = [
        ('bxgy', 'Buy X Get Y'),
        ('percentage', 'Percentage Discount'),
        ('flat_amount', 'Flat Amount Off'),
        ('cart_value', 'Cart Value Discount'),
        ('tiered_price', 'Tiered/Wholesale Price'),
        ('flat_price', 'Flat Price Sale'),
    ]
    
    VALUE_TYPE_CHOICES = [
        ('percent', 'Percentage'),
        ('amount', 'Fixed Amount'),
    ]
    
    BENEFIT_TYPE_CHOICES = [
        ('discount', 'Instant Discount'),
        ('credit_points', 'Loyalty Points (Cashback)'),
    ]
    
    retailer = models.ForeignKey(
        'retailers.RetailerProfile',
        on_delete=models.CASCADE,
        related_name='offers'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    benefit_type = models.CharField(
        max_length=20, 
        choices=BENEFIT_TYPE_CHOICES,
        default='discount'
    )
    
    # Offer Rules
    offer_type = models.CharField(max_length=20, choices=OFFER_TYPE_CHOICES)
    value_type = models.CharField(max_length=10, choices=VALUE_TYPE_CHOICES, default='percent')
    value = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Discount/Points value"
    )
    
    # Constraints & Caps
    min_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_discount_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Max cap for percentage discounts"
    )
    
    # BXGY Specifics
    buy_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Buy X")
    get_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Get Y")
    is_cheapest_free = models.BooleanField(default=True, help_text="If mixing items, cheapest is free")
    
    # Tiered Specifics
    tiered_min_quantity = models.PositiveIntegerField(null=True, blank=True)
    
    # Validity
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0, help_text="Higher number = Higher priority")
    is_stackable = models.BooleanField(default=False, help_text="Can be applied with other offers")
    
    # Usage Limits
    usage_limit_total = models.PositiveIntegerField(null=True, blank=True)
    usage_limit_per_user = models.PositiveIntegerField(null=True, blank=True)
    current_redemptions = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'offer'
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['retailer', 'is_active', 'start_date', 'end_date']),
        ]
        
    def __str__(self):
        return f"{self.name} ({self.get_offer_type_display()})"
        
    def is_valid(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.end_date and now > self.end_date:
            return False
        if now < self.start_date:
            return False
        if self.usage_limit_total and self.current_redemptions >= self.usage_limit_total:
            return False
        return True


class OfferTarget(models.Model):
    """
    Defines which items the offer applies to (Inclusion/Exclusion)
    """
    TARGET_TYPE_CHOICES = [
        ('all_products', 'All Products'),
        ('product', 'Specific Product'),
        ('category', 'Category'),
        ('brand', 'Brand'),
    ]
    
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='targets')
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    
    # References - Nullable because one will be set
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, null=True, blank=True)
    category = models.ForeignKey('products.ProductCategory', on_delete=models.CASCADE, null=True, blank=True)
    brand = models.ForeignKey('products.ProductBrand', on_delete=models.CASCADE, null=True, blank=True)
    
    is_excluded = models.BooleanField(default=False, help_text="Set true to exclude this target from the offer")
    
    class Meta:
        db_table = 'offer_target'
    
    def __str__(self):
        valid = "Excluded" if self.is_excluded else "Included"
        if self.target_type == 'product':
            return f"{valid}: {self.product.name}"
        elif self.target_type == 'category':
            return f"{valid}: Category {self.category.name}"
        elif self.target_type == 'brand':
            return f"{valid}: Brand {self.brand.name}"
        return f"{valid}: All Products"


class OfferRedemption(models.Model):
    """
    Track usages of an offer by customers
    """
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='redemptions')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='applied_offers')
    
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    points_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'offer_redemption'
        indexes = [
            models.Index(fields=['offer', 'customer']),
        ]
