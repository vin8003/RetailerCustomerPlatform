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
    categories = RetailerCategorySerializer(many=True, read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    
    class Meta:
        model = RetailerProfile
        fields = [
            'id', 'username', 'email', 'phone_number', 'shop_name', 
            'shop_description', 'shop_image', 'contact_email', 'contact_phone',
            'whatsapp_number', 'address_line1', 'address_line2', 'city', 
            'state', 'pincode', 'country', 'latitude', 'longitude',
            'business_type', 'gst_number', 'pan_number', 'offers_delivery',
            'offers_pickup', 'delivery_radius', 'serviceable_pincodes', 'minimum_order_amount',
            'is_verified', 'is_active', 'average_rating', 'total_ratings',
            'operating_hours', 'categories', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'is_verified', 'average_rating', 'total_ratings', 'created_at', 'updated_at']


class RetailerProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating retailer profile
    """
    class Meta:
        model = RetailerProfile
        fields = [
            'shop_name', 'shop_description', 'shop_image', 'contact_email', 
            'contact_phone', 'whatsapp_number', 'address_line1', 'address_line2',
            'city', 'state', 'pincode', 'country', 'latitude', 'longitude',
            'business_type', 'gst_number', 'pan_number', 'offers_delivery',
            'offers_pickup', 'delivery_radius', 'serviceable_pincodes', 'minimum_order_amount'
        ]
    
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
    categories = RetailerCategorySerializer(many=True, read_only=True)
    distance = serializers.SerializerMethodField()
    
    class Meta:
        model = RetailerProfile
        fields = [
            'id', 'shop_name', 'shop_description', 'shop_image',
            'city', 'state', 'pincode', 'average_rating', 'total_ratings',
            'offers_delivery', 'offers_pickup', 'delivery_radius',
            'minimum_order_amount', 'categories', 'distance'
        ]
    
    def get_distance(self, obj):
        """Calculate distance from user location if provided"""
        request = self.context.get('request')
        if request and hasattr(request, 'user_location'):
            lat, lng = request.user_location
            return obj.get_distance_from(lat, lng)
        return None


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
            'cashback_percentage', 'max_reward_usage_percent',
            'max_reward_usage_flat', 'conversion_rate', 'is_active',
            'is_referral_enabled', 'referral_reward_points',
            'referee_reward_points', 'min_referral_order_amount'
        ]
