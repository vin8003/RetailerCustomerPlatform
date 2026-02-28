from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from common.utils import generate_upload_path, resize_image


class ProductCategory(models.Model):
    """
    Categories for products
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)  # Icon class name
    parent = models.ForeignKey(
        'self', 
        null=True, 
        blank=True, 
        on_delete=models.CASCADE,
        related_name='subcategories'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'product_category'
        verbose_name_plural = 'Product Categories'
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['parent']),
        ]
    
    def __str__(self):
        return self.name




class ProductBrand(models.Model):
    """
    Brands for products
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to=generate_upload_path, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'product_brand'
        indexes = [
            models.Index(fields=['name']),
        ]
    
    def __str__(self):
        return self.name


class MasterProduct(models.Model):
    """
    Master catalog of products (e.g. from OpenFoodFacts)
    """
    barcode = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        ProductCategory, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='master_products'
    )
    brand = models.ForeignKey(
        ProductBrand, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='master_products'
    )
    image_url = models.URLField(max_length=500, blank=True, null=True)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Maximum Retail Price")
    attributes = models.JSONField(default=dict, blank=True)  # Ingredients, nutrition, etc.
    product_group = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'master_product'
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['barcode']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.barcode})"


class MasterProductImage(models.Model):
    """
    Additional images for master products
    """
    master_product = models.ForeignKey(
        MasterProduct, 
        on_delete=models.CASCADE, 
        related_name='images'
    )
    image = models.ImageField(upload_to=generate_upload_path, blank=True, null=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.image:
            resize_image(self.image)
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'master_product_image'

    def __str__(self):
        return f"Image for {self.master_product.name}"


class Product(models.Model):
    """
    Product model for retailer products
    """
    UNIT_CHOICES = [
        ('piece', 'Piece'),
        ('kg', 'Kilogram'),
        ('gram', 'Gram'),
        ('liter', 'Liter'),
        ('ml', 'Milliliter'),
        ('meter', 'Meter'),
        ('cm', 'Centimeter'),
        ('pack', 'Pack'),
        ('box', 'Box'),
        ('bottle', 'Bottle'),
        ('can', 'Can'),
        ('dozen', 'Dozen'),
    ]
    
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='products'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        ProductCategory, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='products'
    )
    brand = models.ForeignKey(
        ProductBrand, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='products'
    )
    
    # Master Catalog Link
    master_product = models.ForeignKey(
        MasterProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retailer_products'
    )
    barcode = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    
    # Pricing
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    original_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    discount_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Inventory
    quantity = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='piece')
    minimum_order_quantity = models.PositiveIntegerField(default=1)
    maximum_order_quantity = models.PositiveIntegerField(null=True, blank=True)
    
    # Product details
    image = models.ImageField(upload_to=generate_upload_path, blank=True, null=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    images = models.JSONField(default=list, blank=True)  # Additional images
    specifications = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    product_group = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    # SEO and metadata
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)
    slug = models.SlugField(max_length=255, blank=True)
    
    # Status and availability
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    is_draft = models.BooleanField(default=False)  # For incomplete products
    is_seasonal = models.BooleanField(default=False) # For Seasonal Picks lane
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product'
        indexes = [
            models.Index(fields=['retailer', 'is_active']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['brand', 'is_active']),
            models.Index(fields=['name']),
            models.Index(fields=['price']),
            models.Index(fields=['created_at']),
            models.Index(fields=['is_featured']),
            models.Index(fields=['is_seasonal']),
            GinIndex(
                SearchVector('name', 'product_group', 'description', 'tags', config='english'),
                name='product_search_vector_idx'
            ),
        ]
        unique_together = ['retailer', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.retailer.shop_name}"

    def save(self, *args, **kwargs):
        # Calculate discount percentage if original_price is set
        if self.original_price and self.original_price > self.price:
            self.discount_percentage = ((self.original_price - self.price) / self.original_price) * 100
        else:
            self.discount_percentage = Decimal('0.00')
            
        if self.image:
            resize_image(self.image)
            
        super().save(*args, **kwargs)
    
    @property
    def is_in_stock(self):
        """Check if product is in stock"""
        return self.quantity > 0
    
    @property
    def image_display_url(self):
        """Get product image URL or fallback to image_url"""
        if self.image:
            return self.image.url
        if self.image_url:
            return self.image_url
        if self.master_product and self.master_product.image_url:
            return self.master_product.image_url
        return None

    @property
    def discounted_price(self):
        """Final selling price (price field already contains the discounted value)"""
        return self.price
    
    @property
    def savings(self):
        """Calculate savings amount"""
        if self.original_price and self.original_price > self.price:
            return self.original_price - self.price
        return Decimal('0.00')
    
    def can_order_quantity(self, quantity):
        """Check if requested quantity can be ordered"""
        if quantity < self.minimum_order_quantity:
            return False
        if self.maximum_order_quantity and quantity > self.maximum_order_quantity:
            return False
        return quantity <= self.quantity
    
    def reduce_quantity(self, quantity):
        """Reduce product quantity"""
        if self.quantity >= quantity:
            self.quantity -= quantity
            self.save()
            return True
        return False
    
    def increase_quantity(self, quantity):
        """Increase product quantity"""
        self.quantity += quantity
        self.save()


class ProductImage(models.Model):
    """
    Additional images for products
    """
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='additional_images'
    )
    image = models.ImageField(upload_to=generate_upload_path)
    alt_text = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.image:
            resize_image(self.image)
        super().save(*args, **kwargs)
    
    class Meta:
        db_table = 'product_image'
        ordering = ['order', 'created_at']
    
    def __str__(self):
        return f"Image for {self.product.name}"


class ProductReview(models.Model):
    """
    Reviews for products
    """
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='reviews'
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='product_reviews'
    )
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)
    is_verified_purchase = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product_review'
        unique_together = ['product', 'customer']
        indexes = [
            models.Index(fields=['product', 'rating']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.product.name} - {self.rating} stars"


class ProductInventoryLog(models.Model):
    """
    Log for product inventory changes
    """
    LOG_TYPES = [
        ('added', 'Added'),
        ('removed', 'Removed'),
        ('sold', 'Sold'),
        ('returned', 'Returned'),
        ('damaged', 'Damaged'),
        ('expired', 'Expired'),
    ]
    
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='inventory_logs'
    )
    log_type = models.CharField(max_length=20, choices=LOG_TYPES)
    quantity_change = models.IntegerField()
    previous_quantity = models.PositiveIntegerField()
    new_quantity = models.PositiveIntegerField()
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'product_inventory_log'
        indexes = [
            models.Index(fields=['product', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.product.name} - {self.log_type} - {self.quantity_change}"


class ProductUpload(models.Model):
    """
    Track product uploads via Excel
    """
    UPLOAD_STATUS = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='product_uploads'
    )
    file = models.FileField(upload_to=generate_upload_path)
    status = models.CharField(max_length=20, choices=UPLOAD_STATUS, default='pending')
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    successful_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'product_upload'
        indexes = [
            models.Index(fields=['retailer', 'created_at']),
        ]
    
    def __str__(self):
        return f"Upload by {self.retailer.shop_name} - {self.status}"


class ProductUploadSession(models.Model):
    """
    Track visual bulk upload sessions
    """
    SESSION_STATUS = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('discarded', 'Discarded'),
    ]
    
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='upload_sessions'
    )
    name = models.CharField(max_length=255, default="Untitled Session", blank=True)
    status = models.CharField(max_length=20, choices=SESSION_STATUS, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product_upload_session'
        indexes = [
            models.Index(fields=['retailer', 'status']),
        ]
    
    def __str__(self):
        return f"Session {self.id} - {self.retailer.shop_name}"


class UploadSessionItem(models.Model):
    """
    Items within an upload session
    """
    session = models.ForeignKey(
        ProductUploadSession, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    barcode = models.CharField(max_length=50)
    image = models.ImageField(upload_to=generate_upload_path, blank=True, null=True)
    
    # Store partial/draft details: name, price, stock, brand, category etc.
    product_details = models.JSONField(default=dict, blank=True) 
    
    is_processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'upload_session_item'
        indexes = [
            models.Index(fields=['session', 'barcode']),
        ]
    
    def __str__(self):
        return f"Item {self.barcode} in Session {self.session.id}"

class SearchTelemetry(models.Model):
    """
    Log for search queries to track zero-result searches and popular terms
    """
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='search_telemetry',
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    query = models.CharField(max_length=255)
    result_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'search_telemetry'
        indexes = [
            models.Index(fields=['query']),
            models.Index(fields=['created_at']),
            models.Index(fields=['result_count']),
        ]

    def __str__(self):
        return f"Search: '{self.query}' - {self.result_count} results"
