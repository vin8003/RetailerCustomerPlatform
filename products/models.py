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
    name = models.CharField(max_length=100)
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE, 
        related_name='product_categories',
        null=True,
        blank=True
    )
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)  # Icon class name
    image = models.ImageField(upload_to=generate_upload_path, blank=True, null=True)
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
        unique_together = ['retailer', 'name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['parent']),
        ]
    
    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.image:
            from common.utils import resize_image
            resize_image(self.image)
        super().save(*args, **kwargs)




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


class ProductBatch(models.Model):
    """
    Specific inventory batches for products with independent pricing and stock
    """
    product = models.ForeignKey(
        'Product', 
        on_delete=models.CASCADE, 
        related_name='batches'
    )
    retailer = models.ForeignKey(
        'retailers.RetailerProfile', 
        on_delete=models.CASCADE,
        related_name='product_batches'
    )
    batch_number = models.CharField(max_length=100, blank=True, null=True)
    barcode = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    
    # Pricing
    purchase_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
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
    
    # Inventory
    quantity = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    show_on_app = models.BooleanField(default=True)
    additional_barcodes = models.JSONField(default=list, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'product_batch'
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(fields=['retailer', 'barcode']),
            models.Index(fields=['created_at']),
        ]
        unique_together = ['product', 'batch_number'] if 'batch_number' else []

    def __str__(self):
        return f"{self.product.name} - Batch {self.batch_number or self.id} (MRP: {self.original_price})"


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
    additional_barcodes = models.JSONField(default=list, blank=True)
    
    # Pricing
    purchase_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
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
    quantity = models.IntegerField(default=0)
    track_inventory = models.BooleanField(default=True)
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
    has_batches = models.BooleanField(default=False)
    
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

    def sync_inventory_from_batches(self):
        """Update product quantity from sum of active batches (concurrency-safe)"""
        if self.has_batches:
            from django.db import transaction
            with transaction.atomic():
                # Lock the product row to prevent concurrent updates from overwriting
                locked_self = Product.objects.select_for_update().get(pk=self.pk)
                
                active_batches = locked_self.batches.filter(is_active=True)
                locked_self.quantity = active_batches.aggregate(total=models.Sum('quantity'))['total'] or 0
                
                # Sync lowest selling price and its MRP for App visibility
                best_batch = active_batches.filter(quantity__gt=0, show_on_app=True).order_by('price', '-original_price').first()
                if best_batch:
                    locked_self.price = best_batch.price
                    locked_self.original_price = best_batch.original_price
                else:
                    # Fallback: all batches out of stock, use latest active batch price
                    # so App pricing stays up-to-date rather than freezing forever
                    latest_batch = active_batches.order_by('-created_at').first()
                    if latest_batch:
                        locked_self.price = latest_batch.price
                        locked_self.original_price = latest_batch.original_price
                
                locked_self.save(update_fields=['quantity', 'price', 'original_price', 'discount_percentage'])
                
                # Refresh self from the locked row
                self.quantity = locked_self.quantity
                self.price = locked_self.price
                self.original_price = locked_self.original_price
    
    @property
    def is_in_stock(self):
        """Check if product is in stock"""
        if not self.track_inventory:
            return self.is_available
        return self.quantity > 0
    
    @property
    def image_display_url(self):
        """Get product image URL or fallback to image_url"""
        try:
            if self.image and hasattr(self.image, 'url'):
                return self.image.url
        except (ValueError, AttributeError):
            pass
            
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
    
    def can_order_quantity(self, quantity, batch=None):
        """Check if requested quantity can be ordered, optionally from a specific batch"""
        if quantity < self.minimum_order_quantity:
            return False
        if self.maximum_order_quantity and quantity > self.maximum_order_quantity:
            return False
        
        if not self.track_inventory:
            return self.is_available
            
        if self.has_batches and batch:
            return batch.quantity >= quantity
            
        return quantity <= self.quantity
    
    def reduce_quantity(self, quantity, batch=None, allow_negative=False):
        """Reduce product quantity, prioritizing a specific batch if provided"""
        if not self.track_inventory:
            return True
            
        if self.has_batches:
            if batch:
                if allow_negative or batch.quantity >= quantity:
                    batch.quantity -= quantity
                    batch.save()
                    self.sync_inventory_from_batches()
                    return True
            else:
                # FIFO: Reduce from oldest active batches with stock
                remaining = quantity
                batches = self.batches.filter(is_active=True, quantity__gt=0).order_by('created_at')
                
                if not allow_negative and self.quantity < quantity:
                    return False
                    
                for b in batches:
                    if remaining <= 0: break
                    reduction = min(b.quantity, remaining)
                    b.quantity -= reduction
                    b.save()
                    remaining -= reduction
                
                # If still remaining and allow_negative is True, take from the latest batch
                if remaining > 0 and allow_negative:
                    latest_batch = self.batches.filter(is_active=True).order_by('-created_at').first()
                    if latest_batch:
                        latest_batch.quantity -= remaining
                        latest_batch.save()
                        remaining = 0

                self.sync_inventory_from_batches()
                return remaining <= 0
        else:
            if allow_negative or self.quantity >= quantity:
                self.quantity -= quantity
                self.save()
                return True
        return False
    
    def increase_quantity(self, quantity, batch=None):
        """Increase product quantity, optionally for a specific batch"""
        if not self.track_inventory:
            return True
            
        if self.has_batches:
            if batch:
                batch.quantity += quantity
                batch.save()
            else:
                # If no batch provided but has_batches is True, we might need a default batch
                # For now, if no batch, we can't easily increase without knowing which one
                # or we just create/update a default one. But usually increase is via purchase/return.
                b = self.batches.filter(is_active=True).order_by('-created_at').first()
                if b:
                    b.quantity += quantity
                    b.save()
                else:
                    return False
            self.sync_inventory_from_batches()
            return True
        else:
            self.quantity += quantity
            self.save()
            return True
            
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
    batch = models.ForeignKey(
        ProductBatch,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='inventory_logs'
    )
    log_type = models.CharField(max_length=20, choices=LOG_TYPES)
    quantity_change = models.IntegerField()
    previous_quantity = models.IntegerField()
    new_quantity = models.IntegerField()
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


# =====================================================================
# PURCHASE & ERP MODELS
# =====================================================================

class PurchaseInvoice(models.Model):
    """
    Purchase bills from distributors/suppliers
    """
    STATUS_CHOICES = [
        ('UNPAID', 'Unpaid'),
        ('PARTIAL', 'Partially Paid'),
        ('PAID', 'Paid'),
    ]

    retailer = models.ForeignKey(
        'retailers.RetailerProfile',
        on_delete=models.CASCADE,
        related_name='purchase_invoices'
    )
    supplier = models.ForeignKey(
        'retailers.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        related_name='purchase_invoices'
    )
    invoice_number = models.CharField(max_length=100, blank=True, null=True)
    invoice_date = models.DateField()
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNPAID')
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchase_invoice'
        indexes = [
            models.Index(fields=['retailer', 'invoice_date']),
            models.Index(fields=['supplier']),
        ]

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.supplier.company_name if self.supplier else 'Unknown'}"


class PurchaseItem(models.Model):
    """
    Line items within a purchase invoice
    """
    invoice = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        related_name='purchase_history'
    )
    quantity = models.PositiveIntegerField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)  # Rate per unit
    total = models.DecimalField(max_digits=12, decimal_places=2)  # Qty * Rate
    
    # Store whether this invoice updated the master product MRP/Price
    mrp_updated = models.BooleanField(default=False)

    class Meta:
        db_table = 'purchase_item'

    def __str__(self):
        return f"{self.quantity} x {self.product.name if self.product else 'Unknown'} in {self.invoice.invoice_number}"


class SupplierLedger(models.Model):
    """
    Ledger/Khata entries for Suppliers
    """
    TRANSACTION_TYPES = [
        ('CREDIT', 'Credit (Maal Aaya)'),
        ('DEBIT', 'Debit (Paisa Diya)'),
    ]

    supplier = models.ForeignKey(
        'retailers.Supplier',
        on_delete=models.CASCADE,
        related_name='ledger_entries'
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=15, choices=TRANSACTION_TYPES)
    
    # Optional links
    reference_invoice = models.ForeignKey(
        PurchaseInvoice, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='ledger_entries'
    )
    payment_mode = models.CharField(max_length=50, blank=True) # Cash, Bank, UPI etc
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'supplier_ledger'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.transaction_type} of {self.amount} on {self.date}"

