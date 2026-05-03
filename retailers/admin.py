from django.contrib import admin
from .models import (
    RetailerProfile, RetailerOperatingHours, RetailerCategory,
    RetailerCategoryMapping, RetailerReview, RetailerRewardConfig,
    RetailerBlacklist, Supplier, RetailerCustomerMapping, CustomerLedger
)


@admin.register(RetailerProfile)
class RetailerProfileAdmin(admin.ModelAdmin):
    """
    Admin configuration for retailer profiles
    """
    list_display = ['shop_name', 'user', 'city', 'state', 'is_verified', 'is_active', 'average_rating', 'created_at']
    list_filter = ['is_verified', 'is_active', 'city', 'state', 'offers_delivery', 'offers_pickup']
    search_fields = ['shop_name', 'user__username', 'city', 'state', 'business_type']
    ordering = ['-created_at']
    readonly_fields = ['average_rating', 'total_ratings', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'shop_name', 'shop_description', 'shop_image')
        }),
        ('Contact Information', {
            'fields': ('contact_email', 'contact_phone', 'whatsapp_number')
        }),
        ('Address', {
            'fields': ('address_line1', 'address_line2', 'city', 'state', 'pincode', 'country', 'latitude', 'longitude')
        }),
        ('Business Information', {
            'fields': ('business_type', 'gst_number', 'pan_number')
        }),
        ('Service Settings', {
            'fields': ('offers_delivery', 'offers_pickup', 'delivery_radius', 'minimum_order_amount')
        }),
        ('Status', {
            'fields': ('is_verified', 'is_active', 'average_rating', 'total_ratings')
        }),
    )


@admin.register(RetailerOperatingHours)
class RetailerOperatingHoursAdmin(admin.ModelAdmin):
    """
    Admin configuration for retailer operating hours
    """
    list_display = ['retailer', 'day_of_week', 'is_open', 'opening_time', 'closing_time']
    list_filter = ['day_of_week', 'is_open']
    search_fields = ['retailer__shop_name']
    ordering = ['retailer', 'day_of_week']


@admin.register(RetailerCategory)
class RetailerCategoryAdmin(admin.ModelAdmin):
    """
    Admin configuration for retailer categories
    """
    list_display = ['name', 'description', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['name']


@admin.register(RetailerCategoryMapping)
class RetailerCategoryMappingAdmin(admin.ModelAdmin):
    """
    Admin configuration for retailer category mappings
    """
    list_display = ['retailer', 'category', 'is_primary', 'created_at']
    list_filter = ['is_primary', 'category', 'created_at']
    search_fields = ['retailer__shop_name', 'category__name']
    ordering = ['retailer', 'category']


@admin.register(RetailerReview)
class RetailerReviewAdmin(admin.ModelAdmin):
    """
    Admin configuration for retailer reviews
    """
    list_display = ['retailer', 'customer', 'rating', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['retailer__shop_name', 'customer__username']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(RetailerRewardConfig)
class RetailerRewardConfigAdmin(admin.ModelAdmin):
    list_display = ['retailer', 'earning_type', 'loyalty_earning_value', 'is_referral_enabled', 'is_active']
    list_filter = ['earning_type', 'is_referral_enabled', 'is_active']
    search_fields = ['retailer__shop_name']


@admin.register(RetailerBlacklist)
class RetailerBlacklistAdmin(admin.ModelAdmin):
    list_display = ['retailer', 'customer', 'reason', 'created_at']
    list_filter = ['created_at']
    search_fields = ['retailer__shop_name', 'customer__username', 'reason']


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'retailer', 'contact_person', 'phone_number', 'balance_due', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['company_name', 'contact_person', 'phone_number', 'retailer__shop_name']


@admin.register(RetailerCustomerMapping)
class RetailerCustomerMappingAdmin(admin.ModelAdmin):
    list_display = ['retailer', 'customer', 'nickname', 'customer_type', 'current_balance', 'credit_limit', 'total_orders', 'total_spent']
    list_filter = ['customer_type', 'created_at']
    search_fields = ['retailer__shop_name', 'customer__username', 'customer__phone_number', 'nickname', 'tags']
    readonly_fields = ['total_orders', 'total_spent', 'last_order_date', 'created_at', 'updated_at']


@admin.register(CustomerLedger)
class CustomerLedgerAdmin(admin.ModelAdmin):
    list_display = ['mapping', 'transaction_type', 'amount', 'balance_after', 'payment_mode', 'created_at']
    list_filter = ['transaction_type', 'payment_mode', 'created_at']
    search_fields = ['mapping__customer__username', 'mapping__nickname', 'notes']
    readonly_fields = ['created_at']
