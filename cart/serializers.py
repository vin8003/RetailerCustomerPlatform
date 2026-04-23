from rest_framework import serializers
from django.db import transaction
from .models import Cart, CartItem, CartHistory
from products.models import Product
from retailers.models import RetailerProfile


class CartItemSerializer(serializers.ModelSerializer):
    """
    Serializer for cart items
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.CharField(source='product.image_display_url', read_only=True)
    product_price = serializers.DecimalField(source='product.price', max_digits=10, decimal_places=2, read_only=True)
    product_unit = serializers.CharField(source='product.unit', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    stock_quantity = serializers.SerializerMethodField()
    minimum_order_quantity = serializers.IntegerField(source='product.minimum_order_quantity', read_only=True)
    maximum_order_quantity = serializers.IntegerField(source='product.maximum_order_quantity', read_only=True)
    is_available = serializers.BooleanField(read_only=True)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = CartItem
        fields = [
            'id', 'product', 'product_name', 'product_image', 'product_price',
            'product_unit', 'batch', 'batch_number', 'quantity', 'unit_price', 'total_price', 'is_available',
            'stock_quantity', 'minimum_order_quantity', 'maximum_order_quantity',
            'added_at', 'updated_at'
        ]
        read_only_fields = ['id', 'unit_price', 'total_price', 'added_at', 'updated_at']

    def get_stock_quantity(self, obj):
        if obj.batch:
            return obj.batch.quantity
        return obj.product.quantity
    
    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        return value
    
    def validate(self, data):
        """Validate cart item data"""
        product = data.get('product')
        quantity = data.get('quantity', 1)
        
        if product:
            # Check if product is available
            if not product.is_available or not product.is_active:
                raise serializers.ValidationError("Product is not available")
            
            # Check stock availability
            if product.track_inventory and quantity > product.quantity:
                raise serializers.ValidationError(
                    f"Only {product.quantity} items available in stock"
                )
        
        return data


class CartSerializer(serializers.ModelSerializer):
    """
    Serializer for shopping cart
    """
    items = CartItemSerializer(many=True, read_only=True)
    retailer_name = serializers.CharField(source='retailer.shop_name', read_only=True)
    retailer_address = serializers.CharField(source='retailer.full_address', read_only=True)
    retailer_phone = serializers.CharField(source='retailer.contact_phone', read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_empty = serializers.BooleanField(read_only=True)
    minimum_order_amount = serializers.DecimalField(source='retailer.minimum_order_amount', max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = Cart
        fields = [
            'id', 'customer', 'retailer', 'retailer_name', 'retailer_address',
            'retailer_phone', 'items', 'total_items', 'total_amount', 'is_empty',
            'minimum_order_amount', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'customer', 'created_at', 'updated_at']


class AddToCartSerializer(serializers.Serializer):
    """
    Serializer for adding items to cart
    """
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(default=1)
    
    def validate_product_id(self, value):
        """Validate product exists and is available"""
        try:
            product = Product.objects.get(id=value, is_active=True, is_available=True)
            return value
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or not available")
    
    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        return value
    
    def validate(self, data):
        """Validate cart item data"""
        try:
            product = Product.objects.get(id=data['product_id'])
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found")
        
        quantity = data['quantity']
            
        # Check stock availability
        if product.track_inventory and quantity > product.quantity:
             raise serializers.ValidationError(
                f"Only {product.quantity} items available in stock"
            )
        
        # Check if retailer is accepting orders
        if not product.retailer.offers_delivery and not product.retailer.offers_pickup:
            raise serializers.ValidationError("This retailer is currently not accepting orders.")
        
        return data
    
    def create(self, validated_data):
        """Add item to cart with batch-aware fulfillment for multi-batch products"""
        customer = self.context['customer']
        product = Product.objects.get(id=validated_data['product_id'])
        quantity = validated_data['quantity']
        
        # Get or create cart for this retailer
        cart, created = Cart.objects.get_or_create(
            customer=customer,
            retailer=product.retailer
        )
        
        last_item = None
        if product.has_batches:
            # Smart Fulfillment: Use cheapest batches first
            remaining = quantity
            # Get active batches that are allowed on app and have stock
            batches = product.batches.filter(
                is_active=True, 
                show_on_app=True, 
                quantity__gt=0
            ).order_by('price', 'created_at')
            
            for batch in batches:
                if remaining <= 0: break
                
                # Check if we already have this batch in cart to avoid duplicates
                existing_item = cart.items.filter(product=product, batch=batch).first()
                existing_qty = existing_item.quantity if existing_item else 0
                
                # How much more can we take from this batch?
                available_in_batch = batch.quantity - existing_qty
                if available_in_batch <= 0: continue
                
                take = min(remaining, available_in_batch)
                last_item = cart.add_item(product, take, batch)
                remaining -= take
            
            # If still remaining (stock issues or no batches), add to generic/last batch?
            # Actually, validation should have prevented this, but as a fallback:
            if remaining > 0:
                # Fallback to FIFO or just the first available batch even if it's over its limit
                # (The order validation will stop it later if track_inventory is ON)
                batch = product.batches.filter(is_active=True).order_by('price').first()
                last_item = cart.add_item(product, remaining, batch)
        else:
            # Standard single-price product
            last_item = cart.add_item(product, quantity)
        
        # Log cart history
        CartHistory.objects.create(
            customer=customer,
            retailer=product.retailer,
            product=product,
            action='add',
            quantity=quantity,
            price=last_item.unit_price if last_item else product.price
        )
        
        return last_item


class UpdateCartItemSerializer(serializers.Serializer):
    """
    Serializer for updating cart item quantity
    """
    quantity = serializers.IntegerField()
    
    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        return value
    
    def validate(self, data):
        """Validate cart item update"""
        cart_item = self.context['cart_item']
        quantity = data['quantity']
        
        # Check stock availability
        if cart_item.product.track_inventory and quantity > cart_item.product.quantity:
            raise serializers.ValidationError(
                f"Only {cart_item.product.quantity} items available in stock"
            )
        
        # Check if retailer is accepting orders
        retailer = cart_item.cart.retailer
        if not retailer.offers_delivery and not retailer.offers_pickup:
            raise serializers.ValidationError("This retailer is currently not accepting orders.")
        
        return data
    
    def update(self, instance, validated_data):
        """Update cart item quantity"""
        old_quantity = instance.quantity
        new_quantity = validated_data['quantity']
        
        instance.quantity = new_quantity
        instance.save()
        
        # Log cart history
        CartHistory.objects.create(
            customer=instance.cart.customer,
            retailer=instance.cart.retailer,
            product=instance.product,
            action='update',
            quantity=new_quantity,
            price=instance.product.price
        )
        
        return instance


class CartSummarySerializer(serializers.Serializer):
    """
    Serializer for cart summary
    """
    total_items = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    retailer_name = serializers.CharField()
    retailer_id = serializers.IntegerField()
    minimum_order_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    can_checkout = serializers.BooleanField()
    checkout_message = serializers.CharField()
