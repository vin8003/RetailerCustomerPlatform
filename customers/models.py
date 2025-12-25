from django.db import models
from django.conf import settings
from django.core.validators import RegexValidator
from common.utils import generate_upload_path


class CustomerProfile(models.Model):
    """
    Extended profile for customer users
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='customer_profile'
    )
    
    # Personal information
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=10, 
        choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
        blank=True
    )
    profile_image = models.ImageField(
        upload_to=generate_upload_path, 
        blank=True, 
        null=True
    )
    
    # Preferences
    preferred_language = models.CharField(max_length=10, default='en')
    notification_preferences = models.JSONField(default=dict)
    
    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'customer_profile'
    
    def __str__(self):
        return f"{self.user.username} - Customer Profile"


class CustomerAddress(models.Model):
    """
    Address model for customers
    """
    ADDRESS_TYPES = [
        ('home', 'Home'),
        ('office', 'Office'),
        ('other', 'Other'),
    ]
    
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='addresses'
    )
    title = models.CharField(max_length=50)
    address_type = models.CharField(max_length=20, choices=ADDRESS_TYPES, default='home')
    
    # Address details
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    landmark = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(
        max_length=6,
        validators=[RegexValidator(r'^\d{6}$', 'Enter a valid 6-digit pincode')]
    )
    country = models.CharField(max_length=100, default='India')
    
    # Location coordinates (optional)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    
    # Settings
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'customer_address'
        indexes = [
            models.Index(fields=['customer', 'is_default']),
            models.Index(fields=['pincode']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.customer.username}"
    
    @property
    def full_address(self):
        """Return formatted full address"""
        address_parts = [
            self.address_line1,
            self.address_line2,
            self.landmark,
            self.city,
            self.state,
            self.pincode
        ]
        return ', '.join(filter(None, address_parts))
    
    def save(self, *args, **kwargs):
        """Override save to handle default address logic"""
        if self.is_default:
            # Set all other addresses of this customer to non-default
            CustomerAddress.objects.filter(
                customer=self.customer,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        
        super().save(*args, **kwargs)


class CustomerWishlist(models.Model):
    """
    Wishlist/favorites for customers
    """
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='wishlists'
    )
    product = models.ForeignKey(
        'products.Product', 
        on_delete=models.CASCADE, 
        related_name='wishlisted_by'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_wishlist'
        unique_together = ['customer', 'product']
        indexes = [
            models.Index(fields=['customer', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.customer.username} - {self.product.name}"


class CustomerSearchHistory(models.Model):
    """
    Search history for customers
    """
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='search_history'
    )
    query = models.CharField(max_length=255)
    results_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_search_history'
        indexes = [
            models.Index(fields=['customer', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.customer.username} - {self.query}"


class CustomerNotification(models.Model):
    """
    Notifications for customers
    """
    NOTIFICATION_TYPES = [
        ('order_update', 'Order Update'),
        ('promotion', 'Promotion'),
        ('system', 'System'),
        ('reminder', 'Reminder'),
    ]
    
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='notifications'
    )
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_notification'
        indexes = [
            models.Index(fields=['customer', 'is_read']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.customer.username} - {self.title}"


    def __str__(self):
        return f"{self.customer.username} - {self.title}"


class CustomerLoyalty(models.Model):
    """
    Tracks loyalty points for a customer at a specific retailer
    """
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='loyalty_points'
    )
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='customer_loyalty'
    )
    points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'customer_loyalty'
        unique_together = ['customer', 'retailer']
        indexes = [
            models.Index(fields=['customer', 'retailer']),
        ]
        
    def __str__(self):
        return f"{self.customer.username} - {self.retailer.shop_name}: {self.points}"
