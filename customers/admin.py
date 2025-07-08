from django.contrib import admin
from .models import CustomerProfile, CustomerAddress, CustomerWishlist, CustomerNotification, CustomerSearchHistory


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    """
    Admin configuration for customer profiles
    """
    list_display = ['user', 'date_of_birth', 'gender', 'preferred_language', 'is_active', 'created_at']
    list_filter = ['gender', 'preferred_language', 'is_active', 'created_at']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'user__email']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Personal Information', {
            'fields': ('date_of_birth', 'gender', 'profile_image')
        }),
        ('Preferences', {
            'fields': ('preferred_language', 'notification_preferences')
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at')
        }),
    )


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    """
    Admin configuration for customer addresses
    """
    list_display = ['customer', 'title', 'address_type', 'city', 'state', 'pincode', 'is_default', 'is_active']
    list_filter = ['address_type', 'is_default', 'is_active', 'city', 'state']
    search_fields = ['customer__username', 'title', 'city', 'state', 'pincode']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Customer', {
            'fields': ('customer',)
        }),
        ('Address Details', {
            'fields': ('title', 'address_type', 'address_line1', 'address_line2', 'landmark')
        }),
        ('Location', {
            'fields': ('city', 'state', 'pincode', 'country', 'latitude', 'longitude')
        }),
        ('Settings', {
            'fields': ('is_default', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(CustomerWishlist)
class CustomerWishlistAdmin(admin.ModelAdmin):
    """
    Admin configuration for customer wishlist
    """
    list_display = ['customer', 'product', 'created_at']
    list_filter = ['created_at']
    search_fields = ['customer__username', 'product__name']
    ordering = ['-created_at']
    readonly_fields = ['created_at']


@admin.register(CustomerNotification)
class CustomerNotificationAdmin(admin.ModelAdmin):
    """
    Admin configuration for customer notifications
    """
    list_display = ['customer', 'title', 'notification_type', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['customer__username', 'title', 'message']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Customer', {
            'fields': ('customer',)
        }),
        ('Notification Details', {
            'fields': ('notification_type', 'title', 'message')
        }),
        ('Status', {
            'fields': ('is_read', 'created_at')
        }),
    )


@admin.register(CustomerSearchHistory)
class CustomerSearchHistoryAdmin(admin.ModelAdmin):
    """
    Admin configuration for customer search history
    """
    list_display = ['customer', 'query', 'results_count', 'created_at']
    list_filter = ['created_at']
    search_fields = ['customer__username', 'query']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
