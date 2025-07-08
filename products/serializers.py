from rest_framework import serializers
from django.db.models import Avg
from .models import (
    Product, ProductCategory, ProductBrand, ProductImage, 
    ProductReview, ProductUpload
)


class ProductCategorySerializer(serializers.ModelSerializer):
    """
    Serializer for product categories
    """
    subcategories = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'description', 'icon', 'parent', 'subcategories']
    
    def get_subcategories(self, obj):
        """Get subcategories"""
        if obj.subcategories.exists():
            return ProductCategorySerializer(obj.subcategories.filter(is_active=True), many=True).data
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
    category_name = serializers.CharField(source='category.name', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    retailer_name = serializers.CharField(source='retailer.shop_name', read_only=True)
    discounted_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'discounted_price',
            'original_price', 'discount_percentage', 'quantity', 'unit',
            'image', 'category_name', 'brand_name', 'retailer_name',
            'is_in_stock', 'is_featured', 'average_rating', 'review_count',
            'created_at'
        ]
    
    def get_average_rating(self, obj):
        """Calculate average rating"""
        avg_rating = obj.reviews.aggregate(avg_rating=Avg('rating'))['avg_rating']
        return round(avg_rating, 2) if avg_rating else 0
    
    def get_review_count(self, obj):
        """Get review count"""
        return obj.reviews.count()


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for product detail view
    """
    category = ProductCategorySerializer(read_only=True)
    brand = ProductBrandSerializer(read_only=True)
    retailer_name = serializers.CharField(source='retailer.shop_name', read_only=True)
    retailer_id = serializers.IntegerField(source='retailer.id', read_only=True)
    additional_images = ProductImageSerializer(many=True, read_only=True)
    discounted_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)
    savings = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'discounted_price',
            'original_price', 'discount_percentage', 'savings', 'quantity',
            'unit', 'minimum_order_quantity', 'maximum_order_quantity',
            'image', 'images', 'additional_images', 'category', 'brand',
            'retailer_name', 'retailer_id', 'specifications', 'tags',
            'is_in_stock', 'is_featured', 'is_available', 'average_rating',
            'review_count', 'created_at', 'updated_at'
        ]
    
    def get_average_rating(self, obj):
        """Calculate average rating"""
        avg_rating = obj.reviews.aggregate(avg_rating=Avg('rating'))['avg_rating']
        return round(avg_rating, 2) if avg_rating else 0
    
    def get_review_count(self, obj):
        """Get review count"""
        return obj.reviews.count()


class ProductCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating products
    """
    class Meta:
        model = Product
        fields = [
            'name', 'description', 'category', 'brand', 'price',
            'original_price', 'discount_percentage', 'quantity', 'unit',
            'minimum_order_quantity', 'maximum_order_quantity', 'image',
            'images', 'specifications', 'tags', 'is_featured', 'is_available'
        ]
    
    def validate(self, data):
        """Validate product data"""
        if data.get('original_price') and data.get('price'):
            if data['original_price'] < data['price']:
                raise serializers.ValidationError("Original price cannot be less than current price")
        
        if data.get('minimum_order_quantity', 1) > data.get('quantity', 0):
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
            'name', 'description', 'category', 'brand', 'price',
            'original_price', 'discount_percentage', 'quantity', 'unit',
            'minimum_order_quantity', 'maximum_order_quantity', 'image',
            'images', 'specifications', 'tags', 'is_featured', 'is_available'
        ]
    
    def validate(self, data):
        """Validate product data"""
        if data.get('original_price') and data.get('price'):
            if data['original_price'] < data['price']:
                raise serializers.ValidationError("Original price cannot be less than current price")
        
        current_quantity = data.get('quantity', self.instance.quantity)
        min_quantity = data.get('minimum_order_quantity', self.instance.minimum_order_quantity)
        
        if min_quantity > current_quantity:
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
