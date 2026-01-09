from django.db import models
from django.conf import settings
from django.core.validators import RegexValidator
from common.utils import generate_upload_path


class RetailerProfile(models.Model):
    """
    Extended profile for retailer users
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='retailer_profile'
    )
    shop_name = models.CharField(max_length=255)
    shop_description = models.TextField(blank=True)
    shop_image = models.ImageField(
        upload_to=generate_upload_path, 
        blank=True, 
        null=True
    )
    
    # Contact information
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=15, blank=True)
    whatsapp_number = models.CharField(max_length=15, blank=True)
    
    # Address information
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
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
    
    # Business information
    business_type = models.CharField(max_length=100, blank=True)
    gst_number = models.CharField(max_length=15, blank=True)
    pan_number = models.CharField(max_length=10, blank=True)
    
    # Service settings
    offers_delivery = models.BooleanField(default=True)
    offers_pickup = models.BooleanField(default=True)
    delivery_radius = models.PositiveIntegerField(default=5)  # in kilometers
    serviceable_pincodes = models.JSONField(default=list, blank=True)  # List of pincodes
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Status and ratings
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_ratings = models.PositiveIntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'retailer_profile'
        indexes = [
            models.Index(fields=['city', 'state']),
            models.Index(fields=['pincode']),
            models.Index(fields=['is_active', 'is_verified']),
            models.Index(fields=['latitude', 'longitude']),
        ]
    
    def __str__(self):
        return f"{self.shop_name} - {self.city}"
    
    @property
    def full_address(self):
        """Return formatted full address"""
        address_parts = [
            self.address_line1,
            self.address_line2,
            self.city,
            self.state,
            self.pincode
        ]
        return ', '.join(filter(None, address_parts))
    
    def get_distance_from(self, lat, lng):
        """Calculate distance from given coordinates"""
        if not self.latitude or not self.longitude:
            return None
        
        import math
        
        # Haversine formula
        R = 6371  # Earth's radius in kilometers
        
        lat1, lon1 = math.radians(float(self.latitude)), math.radians(float(self.longitude))
        lat2, lon2 = math.radians(lat), math.radians(lng)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c


class RetailerOperatingHours(models.Model):
    """
    Operating hours for retailers
    """
    DAYS_OF_WEEK = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]
    
    retailer = models.ForeignKey(
        RetailerProfile, 
        on_delete=models.CASCADE, 
        related_name='operating_hours'
    )
    day_of_week = models.CharField(max_length=10, choices=DAYS_OF_WEEK)
    is_open = models.BooleanField(default=True)
    opening_time = models.TimeField(null=True, blank=True)
    closing_time = models.TimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'retailer_operating_hours'
        unique_together = ['retailer', 'day_of_week']
    
    def __str__(self):
        return f"{self.retailer.shop_name} - {self.day_of_week}"


class RetailerCategory(models.Model):
    """
    Categories for retailers
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)  # Icon class name
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'retailer_category'
        verbose_name_plural = 'Retailer Categories'
    
    def __str__(self):
        return self.name


class RetailerCategoryMapping(models.Model):
    """
    Many-to-many mapping between retailers and categories
    """
    retailer = models.ForeignKey(
        RetailerProfile, 
        on_delete=models.CASCADE, 
        related_name='categories'
    )
    category = models.ForeignKey(
        RetailerCategory, 
        on_delete=models.CASCADE, 
        related_name='retailers'
    )
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'retailer_category_mapping'
        unique_together = ['retailer', 'category']
    
    def __str__(self):
        return f"{self.retailer.shop_name} - {self.category.name}"


class RetailerReview(models.Model):
    """
    Reviews for retailers
    """
    retailer = models.ForeignKey(
        RetailerProfile, 
        on_delete=models.CASCADE, 
        related_name='reviews'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='retailer_reviews'
    )
    rating = models.PositiveIntegerField()  # 1-5 stars
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'retailer_review'
        unique_together = ['retailer', 'customer']
        indexes = [
            models.Index(fields=['retailer', 'rating']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.retailer.shop_name} - {self.rating} stars"


class RetailerRewardConfig(models.Model):
    """
    Configuration for retailer-specific reward functionality
    """
    retailer = models.OneToOneField(
        RetailerProfile, 
        on_delete=models.CASCADE, 
        related_name='reward_config'
    )
    cashback_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    max_reward_usage_percent = models.DecimalField(max_digits=5, decimal_places=2, default=50.0)
    max_reward_usage_flat = models.DecimalField(max_digits=10, decimal_places=2, default=500.0)
    conversion_rate = models.DecimalField(max_digits=10, decimal_places=2, default=1.0)
    
    # Referral settings
    is_referral_enabled = models.BooleanField(default=False)
    referral_reward_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    referee_reward_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_referral_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'retailer_reward_config'
        verbose_name = 'Retailer Reward Configuration'
        verbose_name_plural = 'Retailer Reward Configurations'
        
    def __str__(self):
        return f"Reward Config for {self.retailer.shop_name}"


class RetailerBlacklist(models.Model):
    """
    List of customers blacklisted by a retailer
    """
    retailer = models.ForeignKey(
        RetailerProfile, 
        on_delete=models.CASCADE, 
        related_name='blacklisted_customers'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='blacklisted_by'
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'retailer_blacklist'
        unique_together = ['retailer', 'customer']
        indexes = [
            models.Index(fields=['retailer', 'customer']),
        ]
    
    def __str__(self):
        return f"{self.customer.username} blacklisted by {self.retailer.shop_name}"
