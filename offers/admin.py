from django.contrib import admin
from .models import Offer, OfferTarget, OfferRedemption

@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ['name', 'retailer', 'offer_type', 'discount_type', 'discount_value', 'is_active', 'start_date', 'end_date']
    list_filter = ['offer_type', 'discount_type', 'is_active', 'start_date', 'end_date']
    search_fields = ['name', 'description', 'retailer__shop_name']
    ordering = ['-created_at']

@admin.register(OfferTarget)
class OfferTargetAdmin(admin.ModelAdmin):
    list_display = ['offer', 'target_type', 'target_id']
    list_filter = ['target_type']
    search_fields = ['offer__name']

@admin.register(OfferRedemption)
class OfferRedemptionAdmin(admin.ModelAdmin):
    list_display = ['offer', 'customer', 'order', 'discount_amount', 'created_at']
    list_filter = ['created_at']
    search_fields = ['offer__name', 'customer__username', 'order__order_number']
