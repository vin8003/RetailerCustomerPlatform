from django.contrib import admin
from .models import (
    Product, ProductCategory, ProductBrand, ProductImage,
    ProductReview, ProductInventoryLog, ProductUpload,
    MasterProduct
)


@admin.register(MasterProduct)
class MasterProductAdmin(admin.ModelAdmin):
    """
    Admin configuration for master products
    """
    list_display = ['name', 'barcode', 'category', 'brand', 'mrp', 'get_nutriscore', 'get_generic_name', 'created_at']
    list_filter = ['category', 'brand', 'created_at']
    search_fields = ['name', 'barcode', 'brand__name', 'attributes']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at', 'attributes']

    def get_nutriscore(self, obj):
        val = obj.attributes.get('nutriscore') if obj.attributes else None
        return val.upper() if val else '-'
    get_nutriscore.short_description = 'NutriScore'
    get_nutriscore.admin_order_field = 'attributes__nutriscore'

    def get_generic_name(self, obj):
        val = obj.attributes.get('generic_name') if obj.attributes else None
        return val[:50] if val else '-'
    get_generic_name.short_description = 'Generic Name'


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    """
    Admin configuration for product categories
    """
    list_display = ['name', 'parent', 'is_active', 'created_at']
    list_filter = ['is_active', 'parent', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['name']


@admin.register(ProductBrand)
class ProductBrandAdmin(admin.ModelAdmin):
    """
    Admin configuration for product brands
    """
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Admin configuration for products
    """
    list_display = ['name', 'barcode', 'retailer', 'category', 'brand', 'price', 'quantity', 'is_active', 'created_at']
    list_filter = ['is_active', 'is_featured', 'is_available', 'category', 'brand', 'unit', 'created_at']
    search_fields = ['name', 'description', 'retailer__shop_name', 'barcode']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at', 'discounted_price', 'is_in_stock', 'savings']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('retailer', 'name', 'description', 'category', 'brand', 'master_product', 'barcode')
        }),
        ('Pricing', {
            'fields': ('price', 'original_price', 'discount_percentage', 'discounted_price', 'savings')
        }),
        ('Inventory', {
            'fields': ('quantity', 'unit', 'minimum_order_quantity', 'maximum_order_quantity', 'is_in_stock')
        }),
        ('Media', {
            'fields': ('image', 'images')
        }),
        ('Additional Info', {
            'fields': ('specifications', 'tags', 'meta_title', 'meta_description', 'slug')
        }),
        ('Status', {
            'fields': ('is_active', 'is_featured', 'is_available')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    """
    Admin configuration for product images
    """
    list_display = ['product', 'alt_text', 'is_primary', 'order', 'created_at']
    list_filter = ['is_primary', 'created_at']
    search_fields = ['product__name', 'alt_text']
    ordering = ['product', 'order']


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    """
    Admin configuration for product reviews
    """
    list_display = ['product', 'customer', 'rating', 'is_verified_purchase', 'created_at']
    list_filter = ['rating', 'is_verified_purchase', 'created_at']
    search_fields = ['product__name', 'customer__username', 'title']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ProductInventoryLog)
class ProductInventoryLogAdmin(admin.ModelAdmin):
    """
    Admin configuration for product inventory logs
    """
    list_display = ['product', 'log_type', 'quantity_change', 'previous_quantity', 'new_quantity', 'created_by', 'created_at']
    list_filter = ['log_type', 'created_at']
    search_fields = ['product__name', 'reason']
    ordering = ['-created_at']
    readonly_fields = ['created_at']


@admin.register(ProductUpload)
class ProductUploadAdmin(admin.ModelAdmin):
    """
    Admin configuration for product uploads
    """
    list_display = ['retailer', 'status', 'total_rows', 'successful_rows', 'failed_rows', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['retailer__shop_name']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'completed_at']
