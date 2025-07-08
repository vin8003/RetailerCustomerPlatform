from django.contrib import admin
from .models import Cart, CartItem, CartSession, CartHistory


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """
    Admin configuration for shopping carts
    """
    list_display = ['customer', 'retailer', 'total_items', 'total_amount', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['customer__username', 'retailer__shop_name']
    ordering = ['-updated_at']
    readonly_fields = ['total_items', 'total_amount', 'is_empty', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Cart Information', {
            'fields': ('customer', 'retailer')
        }),
        ('Cart Summary', {
            'fields': ('total_items', 'total_amount', 'is_empty')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    """
    Admin configuration for cart items
    """
    list_display = ['cart', 'product', 'quantity', 'unit_price', 'total_price', 'is_available', 'added_at']
    list_filter = ['added_at', 'updated_at']
    search_fields = ['cart__customer__username', 'product__name']
    ordering = ['-added_at']
    readonly_fields = ['total_price', 'is_available', 'added_at', 'updated_at']
    
    fieldsets = (
        ('Cart Item Information', {
            'fields': ('cart', 'product', 'quantity', 'unit_price')
        }),
        ('Calculated Fields', {
            'fields': ('total_price', 'is_available')
        }),
        ('Timestamps', {
            'fields': ('added_at', 'updated_at')
        }),
    )


@admin.register(CartSession)
class CartSessionAdmin(admin.ModelAdmin):
    """
    Admin configuration for cart sessions
    """
    list_display = ['session_key', 'retailer', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['session_key', 'retailer__shop_name']
    ordering = ['-updated_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(CartHistory)
class CartHistoryAdmin(admin.ModelAdmin):
    """
    Admin configuration for cart history
    """
    list_display = ['customer', 'retailer', 'product', 'action', 'quantity', 'price', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['customer__username', 'retailer__shop_name', 'product__name']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Action Information', {
            'fields': ('customer', 'retailer', 'product', 'action')
        }),
        ('Details', {
            'fields': ('quantity', 'price')
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )
