from django.contrib import admin
from .models import Order, OrderItem, OrderStatusLog, OrderDelivery, OrderFeedback, OrderReturn


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """
    Admin configuration for orders
    """
    list_display = ['order_number', 'customer', 'retailer', 'status', 'total_amount', 'delivery_mode', 'created_at']
    list_filter = ['status', 'delivery_mode', 'payment_mode', 'created_at']
    search_fields = ['order_number', 'customer__username', 'retailer__shop_name']
    ordering = ['-created_at']
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'customer', 'retailer', 'delivery_address')
        }),
        ('Order Details', {
            'fields': ('delivery_mode', 'payment_mode', 'status', 'special_instructions')
        }),
        ('Pricing', {
            'fields': ('subtotal', 'delivery_fee', 'discount_amount', 'total_amount')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'confirmed_at', 'delivered_at', 'cancelled_at')
        }),
        ('Additional Info', {
            'fields': ('cancellation_reason',)
        }),
    )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    """
    Admin configuration for order items
    """
    list_display = ['order', 'product_name', 'quantity', 'unit_price', 'total_price']
    list_filter = ['product_unit', 'created_at']
    search_fields = ['order__order_number', 'product_name']
    ordering = ['-created_at']


@admin.register(OrderStatusLog)
class OrderStatusLogAdmin(admin.ModelAdmin):
    """
    Admin configuration for order status logs
    """
    list_display = ['order', 'old_status', 'new_status', 'changed_by', 'created_at']
    list_filter = ['old_status', 'new_status', 'created_at']
    search_fields = ['order__order_number', 'changed_by__username']
    ordering = ['-created_at']


@admin.register(OrderDelivery)
class OrderDeliveryAdmin(admin.ModelAdmin):
    """
    Admin configuration for order delivery
    """
    list_display = ['order', 'delivery_status', 'delivery_person_name', 'estimated_delivery_time', 'actual_delivery_time']
    list_filter = ['delivery_status', 'created_at']
    search_fields = ['order__order_number', 'delivery_person_name', 'tracking_id']
    ordering = ['-created_at']


@admin.register(OrderFeedback)
class OrderFeedbackAdmin(admin.ModelAdmin):
    """
    Admin configuration for order feedback
    """
    list_display = ['order', 'customer', 'overall_rating', 'product_quality_rating', 'delivery_rating', 'service_rating', 'created_at']
    list_filter = ['overall_rating', 'product_quality_rating', 'delivery_rating', 'service_rating', 'created_at']
    search_fields = ['order__order_number', 'customer__username', 'comment']
    ordering = ['-created_at']


@admin.register(OrderReturn)
class OrderReturnAdmin(admin.ModelAdmin):
    """
    Admin configuration for order returns
    """
    list_display = ['order', 'customer', 'reason', 'status', 'created_at', 'processed_at']
    list_filter = ['reason', 'status', 'created_at']
    search_fields = ['order__order_number', 'customer__username', 'description']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
