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
    is_available = serializers.BooleanField(read_only=True)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = CartItem
        fields = [
            'id', 'product', 'product_name', 'product_image', 'product_price',
            'product_unit', 'quantity', 'unit_price', 'total_price', 'is_available',
            'added_at', 'updated_at'
        ]
        read_only_fields = ['id', 'unit_price', 'total_price', 'added_at', 'updated_at']
    
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
            if not product.can_order_quantity(quantity):
                raise serializers.ValidationError(
                    f"Only {product.quantity} items available in stock"
                )
            
            # Check minimum and maximum order quantities
            if quantity < product.minimum_order_quantity:
                raise serializers.ValidationError(
                    f"Minimum order quantity is {product.minimum_order_quantity}"
                )
            
            if product.maximum_order_quantity and quantity > product.maximum_order_quantity:
                raise serializers.ValidationError(
                    f"Maximum order quantity is {product.maximum_order_quantity}"
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
        if not product.can_order_quantity(quantity):
            raise serializers.ValidationError(
                f"Only {product.quantity} items available in stock"
            )
        
        # Check minimum and maximum order quantities
        if quantity < product.minimum_order_quantity:
            raise serializers.ValidationError(
                f"Minimum order quantity is {product.minimum_order_quantity}"
            )
        
        if product.maximum_order_quantity and quantity > product.maximum_order_quantity:
            raise serializers.ValidationError(
                f"Maximum order quantity is {product.maximum_order_quantity}"
            )
        
        return data
    
    def create(self, validated_data):
        """Add item to cart"""
        customer = self.context['customer']
        product = Product.objects.get(id=validated_data['product_id'])
        quantity = validated_data['quantity']
        
        # Get or create cart for this retailer
        cart, created = Cart.objects.get_or_create(
            customer=customer,
            retailer=product.retailer
        )
        
        # Add item to cart
        cart_item = cart.add_item(product, quantity)
        
        # Log cart history
        CartHistory.objects.create(
            customer=customer,
            retailer=product.retailer,
            product=product,
            action='add',
            quantity=quantity,
            price=product.price
        )
        
        return cart_item


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
        if not cart_item.product.can_order_quantity(quantity):
            raise serializers.ValidationError(
                f"Only {cart_item.product.quantity} items available in stock"
            )
        
        # Check minimum and maximum order quantities
        if quantity < cart_item.product.minimum_order_quantity:
            raise serializers.ValidationError(
                f"Minimum order quantity is {cart_item.product.minimum_order_quantity}"
            )
        
        if cart_item.product.maximum_order_quantity and quantity > cart_item.product.maximum_order_quantity:
            raise serializers.ValidationError(
                f"Maximum order quantity is {cart_item.product.maximum_order_quantity}"
            )
        
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
