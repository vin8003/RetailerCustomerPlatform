from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import CustomerProfile, CustomerAddress, CustomerWishlist, CustomerNotification
from products.models import Product

User = get_user_model()


class CustomerProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for customer profile
    """
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name')
    
    class Meta:
        model = CustomerProfile
        fields = [
            'id', 'username', 'email', 'phone_number', 'first_name', 'last_name',
            'date_of_birth', 'gender', 'profile_image', 'preferred_language',
            'notification_preferences', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'username', 'email', 'phone_number', 'created_at', 'updated_at']
    
    def update(self, instance, validated_data):
        """Update customer profile and user fields"""
        user_data = validated_data.pop('user', {})
        
        # Update user fields
        if user_data:
            user = instance.user
            for attr, value in user_data.items():
                setattr(user, attr, value)
            user.save()
        
        # Update profile fields
        return super().update(instance, validated_data)


class CustomerAddressSerializer(serializers.ModelSerializer):
    """
    Serializer for customer addresses
    """
    class Meta:
        model = CustomerAddress
        fields = [
            'id', 'title', 'address_type', 'address_line1', 'address_line2',
            'landmark', 'city', 'state', 'pincode', 'country', 'latitude',
            'longitude', 'is_default', 'full_address', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'full_address', 'created_at', 'updated_at']
    
    def validate_pincode(self, value):
        """Validate pincode format"""
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("Pincode must be 6 digits")
        return value
    
    def create(self, validated_data):
        """Create address with customer from context"""
        customer = self.context['customer']
        return CustomerAddress.objects.create(customer=customer, **validated_data)


class CustomerAddressUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating customer addresses
    """
    class Meta:
        model = CustomerAddress
        fields = [
            'title', 'address_type', 'address_line1', 'address_line2',
            'landmark', 'city', 'state', 'pincode', 'country', 'latitude',
            'longitude', 'is_default'
        ]
    
    def validate_pincode(self, value):
        """Validate pincode format"""
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("Pincode must be 6 digits")
        return value


class CustomerWishlistSerializer(serializers.ModelSerializer):
    """
    Serializer for customer wishlist
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(source='product.price', max_digits=10, decimal_places=2, read_only=True)
    product_image = serializers.CharField(source='product.image_display_url', read_only=True)
    retailer_name = serializers.CharField(source='product.retailer.shop_name', read_only=True)
    
    class Meta:
        model = CustomerWishlist
        fields = [
            'id', 'product', 'product_name', 'product_price', 'product_image',
            'retailer_name', 'created_at'
        ]
        read_only_fields = ['id', 'product_name', 'product_price', 'product_image', 'retailer_name', 'created_at']
    
    def create(self, validated_data):
        """Create wishlist item with customer from context"""
        customer = self.context['customer']
        return CustomerWishlist.objects.create(customer=customer, **validated_data)


class CustomerNotificationSerializer(serializers.ModelSerializer):
    """
    Serializer for customer notifications
    """
    class Meta:
        model = CustomerNotification
        fields = [
            'id', 'notification_type', 'title', 'message', 'is_read', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class CustomerDashboardSerializer(serializers.Serializer):
    """
    Serializer for customer dashboard data
    """
    total_orders = serializers.IntegerField()
    pending_orders = serializers.IntegerField()
    delivered_orders = serializers.IntegerField()
    cancelled_orders = serializers.IntegerField()
    total_spent = serializers.DecimalField(max_digits=10, decimal_places=2)
    wishlist_count = serializers.IntegerField()
    addresses_count = serializers.IntegerField()
    unread_notifications = serializers.IntegerField()
    recent_orders = serializers.ListField()
    favorite_retailers = serializers.ListField()


class CustomerSearchHistorySerializer(serializers.Serializer):
    """
    Serializer for customer search history
    """
    query = serializers.CharField()
    results_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
