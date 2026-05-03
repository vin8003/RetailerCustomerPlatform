from rest_framework import serializers
from decimal import Decimal
from django.db import transaction
from django.db.models import Avg, F, Sum
from returns.models import PurchaseReturnItem
from .models import (
    Product, ProductCategory, ProductBrand, ProductImage, 
    ProductReview, ProductUpload, MasterProduct, ProductBatch,
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


class ProductBatchSerializer(serializers.ModelSerializer):
    """
    Serializer for product batches
    """
    class Meta:
        model = ProductBatch
        fields = [
            'id', 'batch_number', 'barcode', 'purchase_price', 
            'price', 'original_price', 'quantity', 'is_active', 'show_on_app'
        ]


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
    batches = serializers.SerializerMethodField()
    quantity = serializers.SerializerMethodField()
    minimum_order_quantity = serializers.SerializerMethodField()
    maximum_order_quantity = serializers.SerializerMethodField()
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'purchase_price', 'discounted_price',
            'original_price', 'discount_percentage', 'quantity', 'track_inventory', 'unit',
            'minimum_order_quantity', 'maximum_order_quantity',
            'image', 'image_url', 'category_name', 'brand_name', 'retailer_name',
            'is_in_stock', 'is_featured', 'is_active', 'is_seasonal', 'is_available',
            'average_rating', 'review_count', 'created_at', 'product_group',
            'active_offer_text', 'is_wishlisted', 'barcode', 'has_batches', 'batches'
        ]

    def get_quantity(self, obj):
        val = obj.quantity
        if val is None: return 0
        if val == val.to_integral_value(): return int(val)
        return float(val.normalize())

    def get_minimum_order_quantity(self, obj):
        val = obj.minimum_order_quantity
        if val is None: return 1
        if val == val.to_integral_value(): return int(val)
        return float(val.normalize())

    def get_maximum_order_quantity(self, obj):
        val = obj.maximum_order_quantity
        if val is None: return None
        if val == val.to_integral_value(): return int(val)
        return float(val.normalize())

    def get_batches(self, obj):
        """Return active batches for POS catalog awareness"""
        if obj.has_batches:
            active_batches = obj.batches.filter(is_active=True).order_by('id')
            return ProductBatchSerializer(active_batches, many=True).data
        return []
    
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
    
    batches = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'price', 'unit', 'image', 'track_inventory', 'quantity', 'has_batches', 'batches']
        
    def get_batches(self, obj):
        if obj.has_batches:
            active_batches = obj.batches.filter(is_active=True).order_by('id')
            return ProductBatchSerializer(active_batches, many=True).data
        return []

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
    images = serializers.SerializerMethodField()
    batches = serializers.SerializerMethodField()
    active_offer_text = serializers.SerializerMethodField()
    offers = serializers.SerializerMethodField()
    is_wishlisted = serializers.SerializerMethodField()
    quantity = serializers.SerializerMethodField()
    minimum_order_quantity = serializers.SerializerMethodField()
    maximum_order_quantity = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'purchase_price', 'discounted_price',
            'original_price', 'discount_percentage', 'savings', 'quantity', 'track_inventory',
            'unit', 'minimum_order_quantity', 'maximum_order_quantity', 'has_batches', 'batches',
            'image', 'image_url', 'images', 'additional_images', 'category', 
            'category_name', 'brand', 'brand_name',
            'retailer_name', 'retailer_id', 'specifications', 'tags',
            'is_in_stock', 'is_featured', 'is_active', 'is_seasonal', 'is_available', 
            'average_rating', 'review_count', 'created_at', 'updated_at',
            'product_group', 'active_offer_text', 'offers', 'is_wishlisted', 'barcode'
        ]

    def get_quantity(self, obj):
        val = obj.quantity
        if val is None: return 0
        if val == val.to_integral_value(): return int(val)
        return float(val.normalize())

    def get_minimum_order_quantity(self, obj):
        val = obj.minimum_order_quantity
        if val is None: return 1
        if val == val.to_integral_value(): return int(val)
        return float(val.normalize())

    def get_maximum_order_quantity(self, obj):
        val = obj.maximum_order_quantity
        if val is None: return None
        if val == val.to_integral_value(): return int(val)
        return float(val.normalize())

    def get_batches(self, obj):
        """Only return active batches for detail view"""
        active_batches = obj.batches.filter(is_active=True).order_by('id')
        return ProductBatchSerializer(active_batches, many=True).data
    
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
            try:
                if obj.image and hasattr(obj.image, 'url'):
                    imgs.append(obj.image.url)
                elif obj.image_url:
                    imgs.append(obj.image_url)
            except (ValueError, AttributeError):
                if obj.image_url:
                    imgs.append(obj.image_url)
                
            # 2. Additional Images (Model)
            for img in obj.additional_images.all():
                try:
                    if img.image and hasattr(img.image, 'url'):
                        imgs.append(img.image.url)
                except (ValueError, AttributeError):
                    pass
                
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
            'barcode', 'master_product', 'product_group', 'is_active', 'is_seasonal', 'has_batches'
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
        
        quantity = data.get('quantity', 0)
        min_order_qty = data.get('minimum_order_quantity', 1)
        if data.get('track_inventory', True) and quantity > 0 and min_order_qty > quantity:
            raise serializers.ValidationError("Minimum order quantity cannot be greater than available quantity")
        
        if data.get('maximum_order_quantity') and data.get('minimum_order_quantity'):
            if data['maximum_order_quantity'] < data['minimum_order_quantity']:
                raise serializers.ValidationError("Maximum order quantity cannot be less than minimum order quantity")
        
        return data
    
    def create(self, validated_data):
        """Create product with retailer from context and initialize first batch"""
        retailer = self.context['retailer']
        has_batches = validated_data.get('has_batches', False)
        product = Product.objects.create(retailer=retailer, **validated_data)
        
        # Always create at least one batch for consistency
        ProductBatch.objects.create(
            product=product,
            retailer=retailer,
            batch_number='INITIAL-STOCK',
            barcode=product.barcode,
            price=product.price,
            original_price=product.original_price,
            purchase_price=product.purchase_price,
            quantity=product.quantity,
            is_active=True
        )
        return product


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
            'barcode', 'master_product', 'product_group', 'is_active', 'is_seasonal', 'has_batches'
        ]
    
    def validate_barcode(self, value):
        if value and self.instance:
            if Product.objects.filter(retailer=self.instance.retailer, barcode=value).exclude(id=self.instance.id).exists():
                raise serializers.ValidationError("A product with this barcode already exists.")
        return value

    def update(self, instance, validated_data):
        """Handle product update and sync batches if provided"""
        import json
        batches_data = self.initial_data.get('batches')
        link_barcode = self.initial_data.get('link_barcode') # Flag for automated batch creation
        
        if isinstance(batches_data, str):
            try:
                batches_data = json.loads(batches_data)
            except:
                batches_data = None

        has_batches = validated_data.get('has_batches', instance.has_batches)
        
        # Logic for 'Link to Existing' - Automated batch/barcode management
        if link_barcode:
            # 1. If product's main barcode is empty, assign it directly
            if not instance.barcode:
                instance.barcode = link_barcode
                instance.save()
                # Also sync the hidden INITIAL-STOCK batch
                instance.batches.filter(batch_number='INITIAL-STOCK').update(barcode=link_barcode)
                # We don't necessarily turn on has_batches for the first barcode link
            
            # 2. If it's a different barcode, handle batch creation
            elif link_barcode != instance.barcode:
                # Check if a batch with this barcode ALREADY exists to prevent duplicates
                existing_batch = instance.batches.filter(barcode=link_barcode, is_active=True).first()
                
                if not existing_batch:
                    has_batches = True
                    validated_data['has_batches'] = True
                    # Create only if it doesn't exist
                    ProductBatch.objects.create(
                        product=instance,
                        retailer=instance.retailer,
                        barcode=link_barcode,
                        price=validated_data.get('price', instance.price),
                        original_price=validated_data.get('original_price', instance.original_price),
                        purchase_price=validated_data.get('purchase_price', instance.purchase_price),
                        quantity=0,
                        is_active=True
                    )
                else:
                    # If it exists, just ensure Multi-Batch is ON so it shows up
                    has_batches = True
                    validated_data['has_batches'] = True

        # Update product
        instance = super().update(instance, validated_data)
        
        if has_batches and batches_data is not None:
            # Sync batches: Create/Update/Mark Inactive
            existing_batch_ids = [b['id'] for b in batches_data if b.get('id')]
            
            # Deactivate batches not in the list
            instance.batches.exclude(id__in=existing_batch_ids).update(is_active=False)
            
            for batch_item in batches_data:
                batch_id = batch_item.get('id')
                batch_fields = {
                    'batch_number': batch_item.get('batch_number'),
                    'barcode': batch_item.get('barcode') or instance.barcode,
                    'price': batch_item.get('price') or instance.price,
                    'original_price': batch_item.get('original_price') or instance.original_price,
                    'purchase_price': batch_item.get('purchase_price') or instance.purchase_price,
                    'quantity': batch_item.get('quantity', 0),
                    'is_active': batch_item.get('is_active', True),
                    'show_on_app': batch_item.get('show_on_app', True),
                }
                
                if batch_id:
                    ProductBatch.objects.filter(id=batch_id, product=instance).update(**batch_fields)
                else:
                    ProductBatch.objects.create(product=instance, retailer=instance.retailer, **batch_fields)
            
            # Sync totals back to product
            instance.sync_inventory_from_batches()
        
        elif not has_batches:
            # If multi-batch is OFF, keep the first batch in sync with product fields
            batch = instance.batches.filter(is_active=True).first()
            if not batch:
                batch = ProductBatch.objects.create(
                    product=instance, 
                    retailer=instance.retailer,
                    batch_number='INITIAL-STOCK',
                    price=instance.price,
                    original_price=instance.original_price,
                    purchase_price=instance.purchase_price,
                    quantity=instance.quantity,
                    barcode=instance.barcode
                )
            else:
                batch.price = instance.price
                batch.original_price = instance.original_price
                batch.purchase_price = instance.purchase_price
                batch.quantity = instance.quantity
                batch.barcode = instance.barcode
                batch.save()
            
        return instance

    def validate(self, data):
        """Validate product data"""
        if data.get('original_price') and data.get('price'):
            if data['original_price'] < data['price']:
                raise serializers.ValidationError("Original price cannot be less than current price")
        
        # Skip standard quantity validation if batches are being used
        if not data.get('has_batches', self.instance.has_batches):
            current_quantity = data.get('quantity', self.instance.quantity)
            min_quantity = data.get('minimum_order_quantity', self.instance.minimum_order_quantity)
            
            track_inv = data.get('track_inventory', self.instance.track_inventory)
            if track_inv and current_quantity > 0 and min_quantity > current_quantity:
                raise serializers.ValidationError("Minimum order quantity cannot be greater than available quantity")
        
        max_quantity = data.get('maximum_order_quantity', self.instance.maximum_order_quantity)
        min_quantity_final = data.get('minimum_order_quantity', self.instance.minimum_order_quantity)
        if max_quantity and max_quantity < min_quantity_final:
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
        fields = ['id', 'product', 'product_name', 'quantity', 'purchase_price', 'total', 'mrp_updated', 'new_price', 'new_original_price', 'returned_quantity', 'net_quantity']
        read_only_fields = ['id']

    returned_quantity = serializers.SerializerMethodField()
    net_quantity = serializers.SerializerMethodField()

    def get_returned_quantity(self, obj):
        return PurchaseReturnItem.objects.filter(purchase_item=obj).aggregate(total=Sum('quantity'))['total'] or 0

    def get_net_quantity(self, obj):
        returned = self.get_returned_quantity(obj)
        return max(0, obj.quantity - returned)


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
            'invoice_date', 'total_amount', 'refund_amount', 'net_amount', 'is_returned', 'paid_amount', 'payment_status',
            'notes', 'created_at', 'items'
        ]

    refund_amount = serializers.SerializerMethodField()
    net_amount = serializers.SerializerMethodField()
    is_returned = serializers.SerializerMethodField()

    def get_refund_amount(self, obj):
        return obj.returns.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

    def get_net_amount(self, obj):
        refund = self.get_refund_amount(obj)
        return obj.total_amount - refund

    def get_is_returned(self, obj):
        return obj.returns.exists()
        read_only_fields = ['id', 'retailer', 'created_at']
        extra_kwargs = {
            'invoice_number': {'required': False, 'allow_blank': True}
        }

    def _validate_invoice_products_for_retailer(self, items_data, retailer):
        """
        Ensure all invoice items belong to the same retailer as the invoice.
        Prevents cross-tenant stock/price mutations.
        """
        if not retailer:
            raise serializers.ValidationError("Retailer context is required for purchase invoices.")

        invalid_product_ids = [
            str(item['product'].id)
            for item in items_data
            if item.get('product') and item['product'].retailer_id != retailer.id
        ]
        if invalid_product_ids:
            raise serializers.ValidationError({
                'items': (
                    "Products must belong to the same retailer as the invoice. "
                    f"Invalid product id(s): {', '.join(invalid_product_ids)}."
                )
            })

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        retailer = validated_data.get('retailer')
        supplier = validated_data.get('supplier')
        from products.models import ProductInventoryLog

        self._validate_invoice_products_for_retailer(items_data, retailer)
        
        with transaction.atomic():
            # Calculate total from items to ensure accuracy
            calculated_total = sum(Decimal(str(item['quantity'])) * Decimal(str(item['purchase_price'])) for item in items_data)
            
            # Auto-generate invoice_number if missing
            invoice_num = validated_data.get('invoice_number', '') or ''
            if not invoice_num.strip():
                from django.utils.timezone import now
                import random, string
                hasher = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
                validated_data['invoice_number'] = f"INV-{now().strftime('%y%m%d')}-{hasher}"

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
                Product.objects.filter(id=item.product.id, retailer=retailer).update(
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

            # (Balance updates are now handled strictly by Django Signals mathematically on Ledger)
                
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
        retailer = instance.retailer
        
        from products.models import ProductInventoryLog

        self._validate_invoice_products_for_retailer(items_data, retailer)
        
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

            # (Reversal balance updates are now handled strictly by Django Signals via cascade deletes)
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
                Product.objects.filter(id=item.product.id, retailer=retailer).update(
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

            # (New balance updates are now handled strictly by Django Signals on Ledger creation)                
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
    reference_invoice_number = serializers.CharField(source='reference_invoice.invoice_number', read_only=True)

    class Meta:
        model = SupplierLedger
        fields = '__all__'
        read_only_fields = ['id', 'created_at']
        fields = '__all__'
        read_only_fields = ['id', 'created_at']
