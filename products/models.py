from django.db import models
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.utils import timezone
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
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    is_active = models.BooleanField(default=True)
    show_on_app = models.BooleanField(default=True)
    additional_barcodes = models.JSONField(default=list, blank=True)
    # Optional until filled. Null-expiry batches stay saleable (OE-136 / F-0030).
    expiry_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'product_batch'
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(
                fields=['product', 'is_active', 'expiry_date'],
                name='product_bat_product_exp_idx',
            ),
            models.Index(fields=['retailer', 'barcode']),
            models.Index(fields=['created_at']),
        ]
        unique_together = ['product', 'batch_number'] if 'batch_number' else []

    def __str__(self):
        return f"{self.product.name} - Batch {self.batch_number or self.id} (MRP: {self.original_price})"

    def is_expired(self, on_date=None):
        """True when expiry_date is set and is before today. Null expiry is never expired."""
        if self.expiry_date is None:
            return False
        if on_date is None:
            on_date = timezone.localdate()
        return self.expiry_date < on_date

    @classmethod
    def saleable_q(cls, on_date=None):
        """
        Default sale policy: forbid expired (expiry_date < today).
        Null-expiry batches remain eligible.
        """
        if on_date is None:
            on_date = timezone.localdate()
        return models.Q(expiry_date__isnull=True) | models.Q(expiry_date__gte=on_date)

    @classmethod
    def fifo_sale_order(cls):
        """Earliest dated expiry first; null expiry last; then oldest created_at."""
        return (F('expiry_date').asc(nulls_last=True), 'created_at')


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
    # OE-106 / F-0023: owned-app list. Null falls back to store ``price``.
    app_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Owned-app selling price. Null means fall back to store price.',
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
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    track_inventory = models.BooleanField(default=True)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='piece')
    minimum_order_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    maximum_order_quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    
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
    
    # KAN-13 Product Grouping / Pack Sizing
    is_parent_bulk = models.BooleanField(default=False, help_text="Is this the master parent bulk product?")
    parent_bulk_product = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='fractional_children',
        help_text="Reference to the parent bulk product keeping master inventory"
    )
    conversion_factor = models.DecimalField(
        max_digits=10, 
        decimal_places=4, 
        null=True, 
        blank=True, 
        validators=[MinValueValidator(Decimal('0.0001'))], 
        help_text="Weight ratio of child weight relative to parent bulk SKU (e.g., 0.10 for 5kg from 50kg)"
    )
    
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
        
        # Trigger fractional inventory sync if this is a parent bulk product
        if self.is_parent_bulk:
            self.sync_fractional_inventories()
        
        # If this is a child product, make sure its stock is synced from parent on save
        elif self.parent_bulk_product:
            parent = self.parent_bulk_product
            
            # Ensure the parent is marked as a master bulk product automatically
            if not parent.is_parent_bulk:
                parent.is_parent_bulk = True
                parent.save(update_fields=['is_parent_bulk'])
                
            if self.conversion_factor and self.conversion_factor > 0:
                expected_qty = parent.quantity / self.conversion_factor
                if self.quantity != expected_qty:
                    self.quantity = expected_qty
                    super().save(update_fields=['quantity'])

    def sync_fractional_inventories(self):
        """Update all child products' quantities based on parent quantity and conversion factor"""
        if self.is_parent_bulk:
            for child in self.fractional_children.filter(is_active=True):
                if child.conversion_factor and child.conversion_factor > 0:
                    child.quantity = self.quantity / child.conversion_factor
                    child.track_inventory = self.track_inventory
                    child.is_available = self.is_available
                    super(Product, child).save(update_fields=['quantity', 'track_inventory', 'is_available'])

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
                    latest_batch = active_batches.order_by('-created_at').first()
                    if latest_batch:
                        locked_self.price = latest_batch.price
                        locked_self.original_price = latest_batch.original_price
                
                locked_self.save(update_fields=['quantity', 'price', 'original_price', 'discount_percentage'])
                
                # Refresh self from the locked row
                self.quantity = locked_self.quantity
                self.price = locked_self.price
                self.original_price = locked_self.original_price
                
                # Trigger fractional inventory sync if parent bulk product
                if locked_self.is_parent_bulk:
                    locked_self.sync_fractional_inventories()
    
    @property
    def is_in_stock(self):
        """Check if product is in stock"""
        if self.parent_bulk_product:
            return self.parent_bulk_product.is_in_stock
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

    def channel_selling_price(self, channel='store', batch=None):
        """Store list is ``price``; app list is ``app_price`` or store fallback."""
        from products.channel_price import resolve_channel_price

        return resolve_channel_price(self, channel, batch=batch)

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
        
        # If this is a child fractional product, check parent stock capacity instead
        if self.parent_bulk_product:
            if self.conversion_factor and self.conversion_factor > 0:
                parent_qty_needed = Decimal(str(quantity)) * self.conversion_factor
                return self.parent_bulk_product.can_order_quantity(parent_qty_needed, batch=None)
            return False
            
        if not self.track_inventory:
            return self.is_available
            
        if self.has_batches and batch:
            if batch.is_expired():
                return False
            return batch.quantity >= quantity

        return quantity <= self.saleable_quantity()

    @staticmethod
    def saleable_quantity_annotation():
        """SUM of active, non-expired batch qty (null expiry stays saleable)."""
        batch_sum = (
            ProductBatch.objects.filter(
                product_id=OuterRef('pk'),
                is_active=True,
            )
            .filter(ProductBatch.saleable_q())
            .values('product_id')
            .annotate(total=Sum('quantity'))
            .values('total')[:1]
        )
        return Coalesce(
            Subquery(
                batch_sum,
                output_field=DecimalField(max_digits=12, decimal_places=3),
            ),
            Decimal('0'),
            output_field=DecimalField(max_digits=12, decimal_places=3),
        )

    @classmethod
    def cache_saleable_quantities(cls, products):
        """Stamp saleable_quantity_annotated on Product instances (one query)."""
        instances = []
        seen = set()
        ids = set()
        for product in products:
            if product is None:
                continue
            if id(product) not in seen:
                instances.append(product)
                seen.add(id(product))
            ids.add(product.pk)
            if product.parent_bulk_product_id:
                ids.add(product.parent_bulk_product_id)
                parent = product.parent_bulk_product
                if parent is not None and id(parent) not in seen:
                    instances.append(parent)
                    seen.add(id(parent))
        if not ids:
            return
        if instances and all(
            hasattr(product, 'saleable_quantity_annotated')
            for product in instances
        ):
            return
        annotated = {
            pk: qty
            for pk, qty in cls.objects.filter(pk__in=ids).annotate(
                saleable_quantity_annotated=cls.saleable_quantity_annotation()
            ).values_list('pk', 'saleable_quantity_annotated')
        }
        for product in instances:
            product.saleable_quantity_annotated = annotated.get(
                product.pk, Decimal('0')
            )

    def saleable_quantity(self):
        """On-hand that may be sold under the default expiry policy."""
        if self.parent_bulk_product:
            if self.conversion_factor and self.conversion_factor > 0:
                return (
                    self.parent_bulk_product.saleable_quantity()
                    / self.conversion_factor
                )
            return Decimal('0')
        if not self.track_inventory:
            return self.quantity
        if self.has_batches:
            annotated = getattr(self, 'saleable_quantity_annotated', None)
            if annotated is not None:
                return annotated
            prefetched = getattr(self, '_prefetched_objects_cache', {}).get('batches')
            if prefetched is not None:
                on_date = timezone.localdate()
                total = Decimal('0')
                for batch in prefetched:
                    if not batch.is_active:
                        continue
                    if batch.expiry_date is None or batch.expiry_date >= on_date:
                        total += batch.quantity
                return total
            total = (
                self.batches.filter(is_active=True)
                .filter(ProductBatch.saleable_q())
                .aggregate(total=models.Sum('quantity'))['total']
            )
            return total if total is not None else Decimal('0')
        return self.quantity

    def reduce_quantity(
        self, quantity, batch=None, allow_negative=False, forbid_expired=True
    ):
        """Reduce product quantity, prioritizing a specific batch if provided"""
        if not self.track_inventory:
            return True
            
        # If this is a child fractional product, deduct stock from parent bulk product
        if self.parent_bulk_product:
            if self.conversion_factor and self.conversion_factor > 0:
                parent_qty_needed = Decimal(str(quantity)) * self.conversion_factor
                success = self.parent_bulk_product.reduce_quantity(
                    parent_qty_needed,
                    batch=None,
                    allow_negative=allow_negative,
                    forbid_expired=forbid_expired,
                )
                if success:
                    self.parent_bulk_product.sync_fractional_inventories()
                return success
            return False
            
        if self.has_batches:
            if batch:
                if forbid_expired and batch.is_expired():
                    return False
                if allow_negative or batch.quantity >= quantity:
                    batch.quantity -= quantity
                    batch.save()
                    self.sync_inventory_from_batches()
                    return True
            else:
                # FIFO: earliest non-null expiry first among saleable qty>0.
                # Null-expiry batches stay eligible and sort after dated rows.
                remaining = quantity
                qs = self.batches.filter(is_active=True, quantity__gt=0)
                if forbid_expired:
                    qs = qs.filter(ProductBatch.saleable_q())
                batches = list(qs.order_by(*ProductBatch.fifo_sale_order()))

                if not allow_negative:
                    available = sum((b.quantity for b in batches), Decimal('0'))
                    if available < quantity:
                        return False

                touched = []
                for b in batches:
                    if remaining <= 0:
                        break
                    reduction = min(b.quantity, remaining)
                    b.quantity -= reduction
                    touched.append(b)
                    remaining -= reduction

                # allow_negative leftover: only a saleable batch when policy forbids expired.
                if remaining > 0 and allow_negative:
                    leftover_qs = self.batches.filter(is_active=True)
                    if forbid_expired:
                        leftover_qs = leftover_qs.filter(ProductBatch.saleable_q())
                    latest_batch = leftover_qs.order_by('-created_at').first()
                    if latest_batch:
                        already = next(
                            (row for row in touched if row.pk == latest_batch.pk),
                            None,
                        )
                        if already is not None:
                            already.quantity -= remaining
                        else:
                            latest_batch.quantity -= remaining
                            touched.append(latest_batch)
                        remaining = 0

                if touched:
                    ProductBatch.objects.bulk_update(touched, ['quantity'])

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
            
        # If this is a child fractional product, restore stock to parent bulk product
        if self.parent_bulk_product:
            if self.conversion_factor and self.conversion_factor > 0:
                parent_qty_added = Decimal(str(quantity)) * self.conversion_factor
                success = self.parent_bulk_product.increase_quantity(parent_qty_added, batch=None)
                if success:
                    self.parent_bulk_product.sync_fractional_inventories()
                return success
            return False
            
        if self.has_batches:
            if batch:
                batch.quantity += quantity
                batch.save()
            else:
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
        ('spoiled', 'Spoiled'),
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
    quantity_change = models.DecimalField(max_digits=12, decimal_places=3)
    previous_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    new_quantity = models.DecimalField(max_digits=12, decimal_places=3)
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
    bill_image = models.ImageField(upload_to=generate_upload_path, blank=True, null=True)
    
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

    def save(self, *args, **kwargs):
        if self.bill_image:
            resize_image(self.bill_image)
        super().save(*args, **kwargs)


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
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
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

