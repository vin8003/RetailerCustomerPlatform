from rest_framework import serializers
from decimal import Decimal
from django.db import transaction
from django.db.models import Avg, F
from .models import (
    Product, ProductCategory, ProductBrand, ProductImage, 
    ProductReview, ProductUpload, MasterProduct,
    ProductUploadSession, UploadSessionItem,
    PurchaseInvoice, PurchaseItem, SupplierLedger
)
import logging

logger = logging.getLogger(__name__)

class ProductCategorySerializer(serializers.ModelSerializer):
    """
    Serializer for product categories
    """
    subcategories = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'description', 'icon', 'image', 'parent', 'subcategories']
    
    def get_subcategories(self, obj):
        """Get subcategories"""
        try:
            if obj.subcategories.exists():
                return ProductCategorySerializer(obj.subcategories.filter(is_active=True), many=True).data
        except Exception:
            pass
        return []


class ProductBrandSerializer(serializers.ModelSerializer):
    """
    Serializer for product brands
    """
    class Meta:
        model = ProductBrand
        fields = ['id', 'name', 'description', 'logo']


class ProductImageSerializer(serializers.ModelSerializer):
    """
    Serializer for product images
    """
    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'alt_text', 'is_primary', 'order']


class ProductReviewSerializer(serializers.ModelSerializer):
    """
    Serializer for product reviews
    """
    customer_name = serializers.CharField(source='customer.first_name', read_only=True)
    
    class Meta:
        model = ProductReview
        fields = [
            'id', 'rating', 'title', 'comment', 'customer_name',
            'is_verified_purchase', 'created_at'
        ]
        read_only_fields = ['id', 'customer_name', 'is_verified_purchase', 'created_at']


class ProductListSerializer(serializers.ModelSerializer):
    """
    Serializer for product list view
    """
    category_name = serializers.SerializerMethodField()
    brand_name = serializers.SerializerMethodField()
    retailer_name = serializers.CharField(source='retailer.shop_name', read_only=True)
    discounted_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    active_offer_text = serializers.SerializerMethodField()
    is_wishlisted = serializers.SerializerMethodField()
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'purchase_price', 'discounted_price',
            'original_price', 'discount_percentage', 'quantity', 'track_inventory', 'unit',
            'minimum_order_quantity', 'maximum_order_quantity',
            'image', 'image_url', 'category_name', 'brand_name', 'retailer_name',
            'is_in_stock', 'is_featured', 'is_active', 'is_seasonal', 'is_available',
            'average_rating', 'review_count', 'created_at', 'product_group',
            'active_offer_text', 'is_wishlisted', 'barcode'
        ]
    
    def get_category_name(self, obj):
        try:
            return obj.category.name if obj.category else None
        except Exception as e:
            logger.error(f"Error getting category name: {e}")
            return None

    def get_brand_name(self, obj):
        try:
            return obj.brand.name if obj.brand else None
        except Exception as e:
            logger.error(f"Error getting brand name: {e}")
            return None

    def get_image(self, obj):
        """Get product image URL or fallback to image_url"""
        try:
            return obj.image_display_url
        except Exception as e:
            logger.error(f"Error getting image url: {e}")
            return None
    
    def get_average_rating(self, obj):
        """Calculate average rating"""
        try:
            if hasattr(obj, 'average_rating_annotated'):
                 return round(obj.average_rating_annotated, 2) if obj.average_rating_annotated else 0
            avg_rating = obj.reviews.aggregate(avg_rating=Avg('rating'))['avg_rating']
            return round(avg_rating, 2) if avg_rating else 0
        except Exception as e:
            logger.error(f"Error getting avg rating: {e}")
            return 0
    
    def get_review_count(self, obj):
        """Get review count"""
        try:
            return getattr(obj, 'review_count_annotated', obj.reviews.count())
        except Exception as e:
            logger.error(f"Error getting review count: {e}")
            return 0

    def get_active_offer_text(self, obj):
        """Get the best active offer name for this product (Optimized)"""
        try:
            # Check if active offers are provided in context (Fixes N+1)
            active_offers = self.context.get('active_offers')
            
            if active_offers is None:
                # Fallback for ad-hoc serialization (expensive)
                from offers.models import Offer
                from django.utils import timezone
                from django.db.models import Q
                active_offers = Offer.objects.filter(
                    retailer=obj.retailer,
                    is_active=True,
                    start_date__lte=timezone.now()
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
                ).order_by('-priority').prefetch_related('targets')
            
            for offer in active_offers:
                # Use pre-fetched targets to avoid N+1 within the loop
                # If targets were prefetched, .all() won't hit DB
                targets = offer.targets.all()
                if not targets: continue
                
                is_match = False
                is_excluded = False
                for target in targets:
                    if target.is_excluded:
                        if target.target_type == 'product' and target.product_id == obj.id:
                            is_excluded = True
                        elif target.target_type == 'category' and target.category_id == obj.category_id:
                            is_excluded = True
                        elif target.target_type == 'brand' and target.brand_id == obj.brand_id:
                            is_excluded = True
                    else:
                        if target.target_type == 'all_products':
                            is_match = True
                        elif target.target_type == 'product' and target.product_id == obj.id:
                            is_match = True
                        elif target.target_type == 'category' and target.category_id == obj.category_id:
                            is_match = True
                        elif target.target_type == 'brand' and target.brand_id == obj.brand_id:
                            is_match = True
                            
                if is_match and not is_excluded:
                    return offer.name
                    
            return None
        except Exception:
            return None

    def get_is_wishlisted(self, obj):
        """Check if product is in authenticated user's wishlist"""
        try:
            wishlisted_product_ids = self.context.get('wishlisted_product_ids')
            if wishlisted_product_ids is not None:
                return obj.id in wishlisted_product_ids
            
            request = self.context.get('request')
            if request and request.user.is_authenticated:
                from customers.models import CustomerWishlist
                return CustomerWishlist.objects.filter(
                    customer=request.user,
                    product=obj
                ).exists()
            return False
        except Exception:
            return False


class ProductSearchSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for product search results
    """
    image = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'price', 'unit', 'image']
        
    def get_image(self, obj):
        try:
            return obj.image_display_url
        except Exception as e:
            logger.error(f"Error getting search image: {e}")
            return None

class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for product detail view
    """
    category = ProductCategorySerializer(read_only=True)
    category_name = serializers.SerializerMethodField()
    brand = ProductBrandSerializer(read_only=True)
    brand_name = serializers.SerializerMethodField()
    retailer_name = serializers.CharField(source='retailer.shop_name', read_only=True)
    retailer_id = serializers.IntegerField(source='retailer.id', read_only=True)
    additional_images = ProductImageSerializer(many=True, read_only=True)
    discounted_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)
    savings = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    active_offer_text = serializers.SerializerMethodField()
    offers = serializers.SerializerMethodField()
    is_wishlisted = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'purchase_price', 'discounted_price',
            'original_price', 'discount_percentage', 'savings', 'quantity', 'track_inventory',
            'unit', 'minimum_order_quantity', 'maximum_order_quantity',
            'image', 'image_url', 'images', 'additional_images', 'category', 
            'category_name', 'brand', 'brand_name',
            'retailer_name', 'retailer_id', 'specifications', 'tags',
            'is_in_stock', 'is_featured', 'is_active', 'is_seasonal', 'is_available', 
            'average_rating', 'review_count', 'created_at', 'updated_at',
            'product_group', 'active_offer_text', 'offers', 'is_wishlisted', 'barcode'
        ]
    
    def get_category_name(self, obj):
        try:
            return obj.category.name if obj.category else None
        except Exception:
            return None

    def get_brand_name(self, obj):
        try:
            return obj.brand.name if obj.brand else None
        except Exception:
            return None

    def get_image(self, obj):
        """Get product image URL or fallback to image_url"""
        try:
            return obj.image_display_url
        except Exception:
            return None

    def get_images(self, obj):
        """Get unified list of all images"""
        try:
            imgs = []
            
            # 1. Primary Image
            if obj.image:
                imgs.append(obj.image.url)
            elif obj.image_url:
                imgs.append(obj.image_url)
                
            # 2. Additional Images (Model)
            for img in obj.additional_images.all():
                imgs.append(img.image.url)
                
            # 3. Additional Images (JSON)
            if obj.images and isinstance(obj.images, list):
                for img in obj.images:
                    if img: imgs.append(str(img))

            # 4. Master Product Images
            if obj.master_product:
                if obj.master_product.image_url and obj.master_product.image_url not in imgs:
                    imgs.append(obj.master_product.image_url)
                
                for mp_img in obj.master_product.images.all():
                    url = mp_img.image.url if mp_img.image else mp_img.image_url
                    if url and url not in imgs:
                        imgs.append(url)
                        
            return list(dict.fromkeys(imgs)) # Remove duplicates preserving order
        except Exception:
            return []
    
    def get_average_rating(self, obj):
        """Calculate average rating"""
        try:
            avg_rating = obj.reviews.aggregate(avg_rating=Avg('rating'))['avg_rating']
            return round(avg_rating, 2) if avg_rating else 0
        except Exception:
            return 0
    
    def get_review_count(self, obj):
        """Get review count"""
        try:
            return obj.reviews.count()
        except Exception:
            return 0
    def get_active_offer_text(self, obj):
        """Get the best active offer name for this product (Optimized)"""
        try:
            active_offers = self.context.get('active_offers')
            if active_offers is None:
                from offers.models import Offer
                from django.utils import timezone
                from django.db.models import Q
                active_offers = Offer.objects.filter(
                    retailer=obj.retailer,
                    is_active=True,
                    start_date__lte=timezone.now()
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
                ).order_by('-priority').prefetch_related('targets')
            
            for offer in active_offers:
                targets = offer.targets.all()
                if not targets: continue
                is_match = False
                is_excluded = False
                for target in targets:
                    if target.is_excluded:
                        if target.target_type == 'product' and target.product_id == obj.id: is_excluded = True
                        elif target.target_type == 'category' and target.category_id == obj.category_id: is_excluded = True
                        elif target.target_type == 'brand' and target.brand_id == obj.brand_id: is_excluded = True
                    else:
                        if target.target_type == 'all_products': is_match = True
                        elif target.target_type == 'product' and target.product_id == obj.id: is_match = True
                        elif target.target_type == 'category' and target.category_id == obj.category_id: is_match = True
                        elif target.target_type == 'brand' and target.brand_id == obj.brand_id: is_match = True
                if is_match and not is_excluded:
                    return offer.name
            return None
        except Exception:
            return None

    def get_offers(self, obj):
        """Get all active offers for this product"""
        try:
            active_offers = self.context.get('active_offers')
            if active_offers is None:
                from offers.models import Offer
                from django.utils import timezone
                from django.db.models import Q
                active_offers = Offer.objects.filter(
                    retailer=obj.retailer,
                    is_active=True,
                    start_date__lte=timezone.now()
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
                ).order_by('-priority').prefetch_related('targets')
            
            matching_offers = []
            for offer in active_offers:
                targets = offer.targets.all()
                if not targets: continue
                is_match = False
                is_excluded = False
                for target in targets:
                    if target.is_excluded:
                        if target.target_type == 'product' and target.product_id == obj.id: is_excluded = True
                        elif target.target_type == 'category' and target.category_id == obj.category_id: is_excluded = True
                        elif target.target_type == 'brand' and target.brand_id == obj.brand_id: is_excluded = True
                    else:
                        if target.target_type == 'all_products': is_match = True
                        elif target.target_type == 'product' and target.product_id == obj.id: is_match = True
                        elif target.target_type == 'category' and target.category_id == obj.category_id: is_match = True
                        elif target.target_type == 'brand' and target.brand_id == obj.brand_id: is_match = True
                if is_match and not is_excluded:
                    matching_offers.append({
                        'id': offer.id,
                        'name': offer.name,
                        'description': offer.description,
                        'offer_type': offer.offer_type,
                        'value': str(offer.value) if offer.value else None
                    })
            return matching_offers
        except Exception:
            return []

    def get_is_wishlisted(self, obj):
        """Check if product is in authenticated user's wishlist"""
        try:
            wishlisted_product_ids = self.context.get('wishlisted_product_ids')
            if wishlisted_product_ids is not None:
                return obj.id in wishlisted_product_ids
            
            request = self.context.get('request')
            if request and request.user.is_authenticated:
                from customers.models import CustomerWishlist
                return CustomerWishlist.objects.filter(
                    customer=request.user,
                    product=obj
                ).exists()
            return False
        except Exception:
            return False


class MasterProductSerializer(serializers.ModelSerializer):
    """
    Serializer for Master Product
    """
    category_name = serializers.SerializerMethodField()
    brand_name = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    
    class Meta:
        model = MasterProduct
        fields = [
            'id', 'barcode', 'name', 'description', 
            'category', 'category_name', 'brand', 'brand_name',
            'image_url', 'images', 'mrp', 'attributes', 'created_at',
            'product_group'
        ]
    
    def get_category_name(self, obj):
        try:
            return obj.category.name if obj.category else None
        except Exception:
            return None

    def get_brand_name(self, obj):
        try:
            return obj.brand.name if obj.brand else None
        except Exception:
            return None

    def get_images(self, obj):
        """Get all images (primary URL + additional)"""
        try:
            imgs = []
            if obj.image_url:
                imgs.append(obj.image_url)
            
            # Additional images
            for img in obj.images.all():  # via related_name='images'
                if img.image:
                    imgs.append(img.image.url)
                elif img.image_url:
                    imgs.append(img.image_url)
            return imgs
        except Exception:
            return []

            return []




class ProductCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating products
    """
    class Meta:
        model = Product
        fields = [
            'name', 'description', 'category', 'brand', 'price', 'purchase_price',
            'original_price', 'discount_percentage', 'quantity', 'track_inventory', 'unit',
            'minimum_order_quantity', 'maximum_order_quantity', 'image',
            'images', 'specifications', 'tags', 'is_featured', 'is_available',
            'barcode', 'master_product', 'product_group', 'is_active', 'is_seasonal'
        ]
    
    def validate_barcode(self, value):
        if value:
            retailer = self.context.get('retailer')
            if retailer and Product.objects.filter(retailer=retailer, barcode=value).exists():
                raise serializers.ValidationError("A product with this barcode already exists.")
        return value

    def validate(self, data):
        """Validate product data"""
        if data.get('original_price') and data.get('price'):
            if data['original_price'] < data['price']:
                raise serializers.ValidationError("Original price cannot be less than current price")
        
        if data.get('track_inventory', True) and data.get('minimum_order_quantity', 1) > data.get('quantity', 0):
            raise serializers.ValidationError("Minimum order quantity cannot be greater than available quantity")
        
        if data.get('maximum_order_quantity') and data.get('minimum_order_quantity'):
            if data['maximum_order_quantity'] < data['minimum_order_quantity']:
                raise serializers.ValidationError("Maximum order quantity cannot be less than minimum order quantity")
        
        return data
    
    def create(self, validated_data):
        """Create product with retailer from context"""
        retailer = self.context['retailer']
        return Product.objects.create(retailer=retailer, **validated_data)


class ProductUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating products
    """
    class Meta:
        model = Product
        fields = [
            'name', 'description', 'category', 'brand', 'price', 'purchase_price',
            'original_price', 'discount_percentage', 'quantity', 'track_inventory', 'unit',
            'minimum_order_quantity', 'maximum_order_quantity', 'image',
            'images', 'specifications', 'tags', 'is_featured', 'is_available',
            'barcode', 'master_product', 'product_group', 'is_active', 'is_seasonal'
        ]
    
    def validate_barcode(self, value):
        if value and self.instance:
            if Product.objects.filter(retailer=self.instance.retailer, barcode=value).exclude(id=self.instance.id).exists():
                raise serializers.ValidationError("A product with this barcode already exists.")
        return value

    def validate(self, data):
        """Validate product data"""
        if data.get('original_price') and data.get('price'):
            if data['original_price'] < data['price']:
                raise serializers.ValidationError("Original price cannot be less than current price")
        
        current_quantity = data.get('quantity', self.instance.quantity)
        min_quantity = data.get('minimum_order_quantity', self.instance.minimum_order_quantity)
        
        track_inv = data.get('track_inventory', self.instance.track_inventory)
        if track_inv and min_quantity > current_quantity:
            raise serializers.ValidationError("Minimum order quantity cannot be greater than available quantity")
        
        max_quantity = data.get('maximum_order_quantity', self.instance.maximum_order_quantity)
        if max_quantity and max_quantity < min_quantity:
            raise serializers.ValidationError("Maximum order quantity cannot be less than minimum order quantity")
        
        return data


class ProductUploadSerializer(serializers.ModelSerializer):
    """
    Serializer for product uploads
    """
    class Meta:
        model = ProductUpload
        fields = [
            'id', 'file', 'status', 'total_rows', 'processed_rows',
            'successful_rows', 'failed_rows', 'error_log', 'created_at',
            'completed_at'
        ]
        read_only_fields = [
            'id', 'status', 'total_rows', 'processed_rows', 'successful_rows',
            'failed_rows', 'error_log', 'created_at', 'completed_at'
        ]
    
    def create(self, validated_data):
        """Create product upload with retailer from context"""
        retailer = self.context['retailer']
        return ProductUpload.objects.create(retailer=retailer, **validated_data)


class ProductBulkUploadSerializer(serializers.Serializer):
    """
    Serializer for bulk product upload via Excel
    """
    file = serializers.FileField()
    
    def validate_file(self, value):
        """Validate uploaded file"""
        if not value.name.endswith(('.xlsx', '.xls', '.csv')):
            raise serializers.ValidationError("File must be Excel (.xlsx, .xls) or CSV format")
        
        # Check file size (10MB limit)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("File size cannot exceed 10MB")
        
        return value


class ProductStatsSerializer(serializers.Serializer):
    """
    Serializer for product statistics
    """
    total_products = serializers.IntegerField()
    active_products = serializers.IntegerField()
    out_of_stock_products = serializers.IntegerField()
    low_stock_products = serializers.IntegerField()
    featured_products = serializers.IntegerField()
    total_categories = serializers.IntegerField()
    total_brands = serializers.IntegerField()
    average_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    top_categories = serializers.ListField()
    recent_products = serializers.ListField()


class UploadSessionItemSerializer(serializers.ModelSerializer):
    """
    Serializer for upload session items
    """
    class Meta:
        model = UploadSessionItem
        fields = ['id', 'barcode', 'image', 'product_details', 'is_processed', 'created_at']
        read_only_fields = ['id', 'is_processed', 'created_at']


class ProductUploadSessionSerializer(serializers.ModelSerializer):
    """
    Serializer for product upload sessions
    """
    items = UploadSessionItemSerializer(many=True, read_only=True)
    
    class Meta:
        model = ProductUploadSession
        fields = ['id', 'name', 'status', 'created_at', 'updated_at', 'items']
        read_only_fields = ['id', 'status', 'created_at', 'updated_at', 'items']


class PurchaseItemSerializer(serializers.ModelSerializer):
    """
    Serializer for Purchase Items
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    # Fields to allow updating product prices during purchase
    new_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, write_only=True)
    new_original_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, write_only=True)

    class Meta:
        model = PurchaseItem
        fields = ['id', 'product', 'product_name', 'quantity', 'purchase_price', 'total', 'mrp_updated', 'new_price', 'new_original_price']
        read_only_fields = ['id']


class PurchaseInvoiceSerializer(serializers.ModelSerializer):
    """
    Serializer for Purchase Invoices
    """
    items = PurchaseItemSerializer(many=True)
    supplier_name = serializers.CharField(source='supplier.company_name', read_only=True)

    class Meta:
        model = PurchaseInvoice
        fields = [
            'id', 'retailer', 'supplier', 'supplier_name', 'invoice_number',
            'invoice_date', 'total_amount', 'paid_amount', 'payment_status',
            'notes', 'created_at', 'items'
        ]
        read_only_fields = ['id', 'retailer', 'created_at']

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        retailer = validated_data.get('retailer')
        supplier = validated_data.get('supplier')
        from products.models import ProductInventoryLog
        
        with transaction.atomic():
            # Calculate total from items to ensure accuracy
            calculated_total = sum(Decimal(str(item['quantity'])) * Decimal(str(item['purchase_price'])) for item in items_data)
            
            # 1. Create Invoice (overwrite total_amount with calculated value)
            validated_data['total_amount'] = calculated_total
            invoice = PurchaseInvoice.objects.create(**validated_data)
            
            for item_data in items_data:
                # Remove write-only fields for Product model updates
                new_price = item_data.pop('new_price', None)
                new_orig_price = item_data.pop('new_original_price', None)
                
                # 2. Create PurchaseItem
                item = PurchaseItem.objects.create(invoice=invoice, **item_data)
                
                # 3. Update Product Stock & Prices (Atomically)
                Product.objects.filter(id=item.product.id).update(
                    quantity=F('quantity') + item.quantity,
                    purchase_price=item.purchase_price
                )
                
                # Refresh product for logs and price updates
                product = item.product
                product.refresh_from_db()
                
                if new_price:
                    product.price = new_price
                if new_orig_price:
                    product.original_price = new_orig_price
                product.save()
                
                # 4. Log Inventory Change
                ProductInventoryLog.objects.create(
                    product=product,
                    created_by=self.context['request'].user,
                    quantity_change=item.quantity,
                    previous_quantity=product.quantity - item.quantity,
                    new_quantity=product.quantity,
                    log_type='added',
                    reason=f'Purchase Inward: Invoice #{invoice.invoice_number}'
                )

            # 5. Update Supplier Balance (Atomically)
            if supplier:
                unpaid_amount = invoice.total_amount - invoice.paid_amount
                from retailers.models import Supplier
                Supplier.objects.filter(id=supplier.id).update(
                    balance_due=F('balance_due') + unpaid_amount
                )
                
                # 6. Create Ledger Entry (Credit)
                SupplierLedger.objects.create(
                    supplier=supplier,
                    date=invoice.invoice_date,
                    amount=invoice.total_amount,
                    transaction_type='CREDIT',
                    reference_invoice=invoice,
                    notes=f"Purchase Bill #{invoice.invoice_number}"
                )
                
                # 7. If there was a partial payment, create a Debit entry too
                if invoice.paid_amount > 0:
                    SupplierLedger.objects.create(
                        supplier=supplier,
                        date=invoice.invoice_date,
                        amount=invoice.paid_amount,
                        transaction_type='DEBIT',
                        reference_invoice=invoice,
                        notes=f"Paid against Bill #{invoice.invoice_number}"
                    )
            return invoice
            
    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', [])
        new_supplier = validated_data.get('supplier', instance.supplier)
        
        from products.models import ProductInventoryLog
        
        with transaction.atomic():
            # --- 1. REVERSE OLD IMPACTS ---
            
            # Reverse Stock (Convert to list for safety)
            old_items = list(instance.items.all())
            for old_item in old_items:
                product = old_item.product
                Product.objects.filter(id=product.id).update(
                    quantity=F('quantity') - old_item.quantity
                )
                
                # Log stock reversal
                product.refresh_from_db()
                ProductInventoryLog.objects.create(
                    product=product,
                    created_by=self.context['request'].user,
                    quantity_change=-old_item.quantity,
                    previous_quantity=product.quantity + old_item.quantity,
                    new_quantity=product.quantity,
                    log_type='removed',
                    reason=f'Purchase Edit (Reversal): Invoice #{instance.invoice_number}'
                )

            # Reverse Supplier Balance (From OLD Supplier - Atomically)
            if instance.supplier:
                old_unpaid = instance.total_amount - instance.paid_amount
                from retailers.models import Supplier
                Supplier.objects.filter(id=instance.supplier.id).update(
                    balance_due=F('balance_due') - old_unpaid
                )

            # Clean Up Related Data
            instance.items.all().delete()
            SupplierLedger.objects.filter(reference_invoice=instance).delete()

            # --- 2. APPLY NEW CHANGES ---
            
            # Recalculate New Total
            new_total = sum(Decimal(str(item['quantity'])) * Decimal(str(item['purchase_price'])) for item in items_data)
            validated_data['total_amount'] = new_total
            
            # Update Invoice Instance
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            # Apply New Stock
            for item_data in items_data:
                new_price = item_data.pop('new_price', None)
                new_orig_price = item_data.pop('new_original_price', None)
                
                item = PurchaseItem.objects.create(invoice=instance, **item_data)
                
                # Atomic update
                Product.objects.filter(id=item.product.id).update(
                    quantity=F('quantity') + item.quantity,
                    purchase_price=item.purchase_price
                )
                
                product = item.product
                product.refresh_from_db()
                
                if new_price:
                    product.price = new_price
                if new_orig_price:
                    product.original_price = new_orig_price
                product.save()
                
                ProductInventoryLog.objects.create(
                    product=product,
                    created_by=self.context['request'].user,
                    quantity_change=item.quantity,
                    previous_quantity=product.quantity - item.quantity,
                    new_quantity=product.quantity,
                    log_type='added',
                    reason=f'Purchase Updated: Invoice #{instance.invoice_number}'
                )

            # Apply New Supplier Balance (To NEW Supplier - Atomically)
            if new_supplier:
                new_unpaid = instance.total_amount - instance.paid_amount
                from retailers.models import Supplier
                Supplier.objects.filter(id=new_supplier.id).update(
                    balance_due=F('balance_due') + new_unpaid
                )
                
                # Re-create Ledger
                SupplierLedger.objects.create(
                    supplier=new_supplier,
                    date=instance.invoice_date,
                    amount=instance.total_amount,
                    transaction_type='CREDIT',
                    reference_invoice=instance,
                    notes=f"Purchase Bill (Updated) #{instance.invoice_number}"
                )
                
                if instance.paid_amount > 0:
                    SupplierLedger.objects.create(
                        supplier=new_supplier,
                        date=instance.invoice_date,
                        amount=instance.paid_amount,
                        transaction_type='DEBIT',
                        reference_invoice=instance,
                        notes=f"Paid (Updated) against Bill #{instance.invoice_number}"
                    )

            return instance

class SupplierLedgerSerializer(serializers.ModelSerializer):
    """
    Serializer for Supplier Ledger
    """
    class Meta:
        model = SupplierLedger
        fields = '__all__'
        read_only_fields = ['id', 'created_at']
