from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    RetailerProfile, RetailerOperatingHours, RetailerCategory,
    RetailerCategoryMapping, RetailerReview, RetailerRewardConfig
)

User = get_user_model()


class RetailerCategorySerializer(serializers.ModelSerializer):
    """
    Serializer for retailer categories
    """
    class Meta:
        model = RetailerCategory
        fields = ['id', 'name', 'description', 'icon']


class RetailerOperatingHoursSerializer(serializers.ModelSerializer):
    """
    Serializer for retailer operating hours
    """
    class Meta:
        model = RetailerOperatingHours
        fields = ['day_of_week', 'is_open', 'opening_time', 'closing_time']


class RetailerProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for retailer profile
    """
    operating_hours = RetailerOperatingHoursSerializer(many=True, read_only=True)
    is_currently_open = serializers.SerializerMethodField()
    next_open_time = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    is_phone_verified = serializers.BooleanField(source='user.is_phone_verified', read_only=True)
    
    # Reward Configuration
    is_referral_enabled = serializers.BooleanField(source='reward_config.is_referral_enabled', read_only=True)
    referral_reward_points = serializers.DecimalField(source='reward_config.referral_reward_points', max_digits=10, decimal_places=2, read_only=True)
    min_referral_order_amount = serializers.DecimalField(source='reward_config.min_referral_order_amount', max_digits=10, decimal_places=2, read_only=True)
    cashback_percentage = serializers.DecimalField(source='reward_config.cashback_percentage', max_digits=5, decimal_places=2, read_only=True)
    loyalty_earning_type = serializers.CharField(source='reward_config.earning_type', read_only=True)
    loyalty_earning_value = serializers.DecimalField(source='reward_config.loyalty_earning_value', max_digits=10, decimal_places=2, read_only=True)
    loyalty_min_order_value = serializers.DecimalField(source='reward_config.loyalty_min_order_value', max_digits=10, decimal_places=2, read_only=True)
    is_reward_active = serializers.BooleanField(source='reward_config.is_active', read_only=True)
    
    class Meta:
        model = RetailerProfile
        fields = [
            'id', 'username', 'email', 'phone_number', 'is_phone_verified', 'shop_name', 
            'shop_description', 'shop_image', 'contact_email', 'contact_phone',
            'whatsapp_number', 'address_line1', 'address_line2', 'city', 
            'state', 'pincode', 'country', 'latitude', 'longitude',
            'business_type', 'gst_number', 'pan_number', 'upi_id', 'upi_qr_code', 
            'offers_delivery',
            'offers_pickup', 'delivery_radius', 'serviceable_pincodes', 'minimum_order_amount',
            'delivery_charge', 'free_delivery_threshold',
            'is_verified', 'is_active', 'average_rating', 'total_ratings',
            'is_reward_active', 'is_referral_enabled', 'referral_reward_points', 'min_referral_order_amount', 
            'cashback_percentage', 'loyalty_earning_type', 'loyalty_earning_value', 'loyalty_min_order_value',
            'operating_hours', 'is_currently_open', 'next_open_time', 'categories', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'is_verified', 'average_rating', 'total_ratings', 'created_at', 'updated_at']

    def get_is_currently_open(self, obj):
        from common.utils import get_retailer_status
        status = get_retailer_status(obj)
        return status.get('is_open', False)

    def get_next_open_time(self, obj):
        from common.utils import get_retailer_status
        status = get_retailer_status(obj)
        return status.get('next_status_time', None)

    def get_categories(self, obj):
        mappings = obj.categories.all()
        categories = [mapping.category for mapping in mappings]
        return RetailerCategorySerializer(categories, many=True).data


class RetailerProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating retailer profile
    """
    def to_internal_value(self, data):
        # Handle cases where image fields are sent as URLs (meaning no change)
        # We create a mutable copy if it's a QueryDict
        if hasattr(data, 'getlist'):
            mutable_data = {}
            for key in data.keys():
                if key in ['serviceable_pincodes', 'categories']:
                    mutable_data[key] = data.getlist(key)
                else:
                    # For other fields, keep the list if length > 1, else scalar
                    # DRF handles scalars for list fields natively if not using dict()
                    lst = data.getlist(key)
                    mutable_data[key] = lst[0] if len(lst) == 1 else lst
            data = mutable_data
        elif hasattr(data, 'dict'):
            data = data.dict()
            
        for field in ['shop_image', 'upi_qr_code']:
            if field in data and isinstance(data[field], str) and data[field].startswith('http'):
                data.pop(field)
        
        return super().to_internal_value(data)

    categories = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )

    class Meta:
        model = RetailerProfile
        fields = [
            'shop_name', 'shop_description', 'shop_image', 'contact_email', 
            'contact_phone', 'whatsapp_number', 'address_line1', 'address_line2',
            'city', 'state', 'pincode', 'country', 'latitude', 'longitude',
            'business_type', 'gst_number', 'pan_number', 'upi_id', 'upi_qr_code', 
            'offers_delivery',
            'offers_pickup', 'delivery_radius', 'serviceable_pincodes', 'minimum_order_amount',
            'delivery_charge', 'free_delivery_threshold', 'categories'
        ]
        
    def create(self, validated_data):
        categories_data = validated_data.pop('categories', [])
        instance = super().create(validated_data)
        self._update_categories(instance, categories_data)
        return instance

    def update(self, instance, validated_data):
        categories_data = validated_data.pop('categories', None)
        instance = super().update(instance, validated_data)
        if categories_data is not None:
            self._update_categories(instance, categories_data)
        return instance

    def _update_categories(self, instance, categories_data):
        from .models import RetailerCategoryMapping, RetailerCategory
        # Clear existing
        RetailerCategoryMapping.objects.filter(retailer=instance).delete()
        # Add new
        for cat_id in categories_data:
            try:
                category = RetailerCategory.objects.get(id=cat_id)
                RetailerCategoryMapping.objects.create(retailer=instance, category=category)
            except RetailerCategory.DoesNotExist:
                pass
    
    def validate_pincode(self, value):
        """Validate pincode format"""
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("Pincode must be 6 digits")
        return value
    
    def validate_gst_number(self, value):
        """Validate GST number format"""
        if value and len(value) != 15:
            raise serializers.ValidationError("GST number must be 15 characters")
        return value
    
    def validate_pan_number(self, value):
        """Validate PAN number format"""
        if value and len(value) != 10:
            raise serializers.ValidationError("PAN number must be 10 characters")
        return value


class RetailerListSerializer(serializers.ModelSerializer):
    """
    Serializer for retailer list view
    """
    categories = serializers.SerializerMethodField()
    distance = serializers.SerializerMethodField()
    is_currently_open = serializers.SerializerMethodField()
    next_open_time = serializers.SerializerMethodField()
    
    class Meta:
        model = RetailerProfile
        fields = [
            'id', 'shop_name', 'shop_description', 'shop_image',
            'city', 'state', 'pincode', 'average_rating', 'total_ratings',
            'offers_delivery', 'offers_pickup', 'delivery_radius',
            'minimum_order_amount', 'categories', 'distance', 'is_currently_open', 'next_open_time'
        ]
    
    def get_is_currently_open(self, obj):
        from common.utils import get_retailer_status
        status = get_retailer_status(obj)
        return status.get('is_open', False)

    def get_next_open_time(self, obj):
        from common.utils import get_retailer_status
        status = get_retailer_status(obj)
        return status.get('next_status_time', None)
    
    def get_distance(self, obj):
        """Calculate distance from user location if provided"""
        request = self.context.get('request')
        if request and hasattr(request, 'user_location'):
            lat, lng = request.user_location
            return obj.get_distance_from(lat, lng)
        return None

    def get_categories(self, obj):
        mappings = obj.categories.all()
        categories = [mapping.category for mapping in mappings]
        return RetailerCategorySerializer(categories, many=True).data


class RetailerReviewSerializer(serializers.ModelSerializer):
    """
    Serializer for retailer reviews
    """
    customer_name = serializers.CharField(source='customer.first_name', read_only=True)
    
    class Meta:
        model = RetailerReview
        fields = ['id', 'rating', 'comment', 'customer_name', 'created_at']
        read_only_fields = ['id', 'customer_name', 'created_at']
    
    def validate_rating(self, value):
        """Validate rating is between 1-5"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value


class RetailerCreateReviewSerializer(serializers.ModelSerializer):
    """
    Serializer for creating retailer reviews
    """
    class Meta:
        model = RetailerReview
        fields = ['rating', 'comment']
    
    def validate_rating(self, value):
        """Validate rating is between 1-5"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def create(self, validated_data):
        """Create review and update retailer average rating"""
        retailer = self.context['retailer']
        customer = self.context['customer']
        
        # Create or update review
        review, created = RetailerReview.objects.update_or_create(
            retailer=retailer,
            customer=customer,
            defaults=validated_data
        )
        
        # Update retailer average rating
        self.update_retailer_rating(retailer)
        
        return review
    
    def update_retailer_rating(self, retailer):
        """Update retailer average rating"""
        reviews = RetailerReview.objects.filter(retailer=retailer)
        if reviews.exists():
            total_rating = sum(review.rating for review in reviews)
            retailer.average_rating = total_rating / reviews.count()
            retailer.total_ratings = reviews.count()
            retailer.save()


class RetailerOperatingHoursUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating operating hours
    """
    class Meta:
        model = RetailerOperatingHours
        fields = ['day_of_week', 'is_open', 'opening_time', 'closing_time']
    
    def validate(self, data):
        """Validate opening and closing times"""
        if data.get('is_open') and data.get('opening_time') and data.get('closing_time'):
            if data['opening_time'] >= data['closing_time']:
                raise serializers.ValidationError("Opening time must be before closing time")
        return data


class RetailerRewardConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for retailer reward configuration
    """
    class Meta:
        model = RetailerRewardConfig
        fields = [
            'earning_type', 'loyalty_earning_value', 'loyalty_min_order_value',
            'cashback_percentage', 'max_reward_usage_percent',
            'max_reward_usage_flat', 'conversion_rate', 'is_active',
            'is_referral_enabled', 'referral_reward_points',
            'referee_reward_points', 'min_referral_order_amount'
        ]
