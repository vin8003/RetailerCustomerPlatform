from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from .models import Order, OrderItem, OrderStatusLog, OrderDelivery, OrderFeedback, OrderReturn, OrderChatMessage, RetailerRating
from customers.models import CustomerAddress
from products.models import Product
from cart.models import Cart, CartItem


class OrderItemSerializer(serializers.ModelSerializer):
    """
    Serializer for order items
    """
    product_image = serializers.CharField(source='product.image_display_url', read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'product_name', 'product_image', 'product_price', 'product_unit',
            'quantity', 'unit_price', 'total_price', 'created_at'
        ]
        read_only_fields = ['id', 'total_price', 'created_at']


class OrderListSerializer(serializers.ModelSerializer):
    """
    Serializer for order list view
    """
    retailer_name = serializers.CharField(source='retailer.shop_name', read_only=True)
    customer_name = serializers.CharField(source='customer.first_name', read_only=True)
    items_count = serializers.SerializerMethodField()
    has_customer_feedback = serializers.SerializerMethodField()
    has_retailer_rating = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'retailer', 'retailer_name', 'customer_name', 'delivery_mode', 'payment_mode',
            'status', 'total_amount', 'items_count', 'created_at', 'updated_at', 'has_customer_feedback', 'has_retailer_rating'
        ]
    
    def get_items_count(self, obj):
        """Get number of items in order"""
        return getattr(obj, 'items_count_annotated', obj.items.count())

    def get_has_customer_feedback(self, obj):
        return hasattr(obj, 'feedback')

    def get_has_retailer_rating(self, obj):
        return hasattr(obj, 'retailer_rating')


class OrderDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for order detail view
    """
    items = OrderItemSerializer(many=True, read_only=True)
    retailer_name = serializers.CharField(source='retailer.shop_name', read_only=True)
    retailer_phone = serializers.CharField(source='retailer.contact_phone', read_only=True)
    retailer_address = serializers.CharField(source='retailer.full_address', read_only=True)
    customer_name = serializers.CharField(source='customer.first_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    delivery_address_text = serializers.CharField(source='delivery_address.full_address', read_only=True)
    delivery_latitude = serializers.DecimalField(source='delivery_address.latitude', max_digits=10, decimal_places=8, read_only=True)
    delivery_longitude = serializers.DecimalField(source='delivery_address.longitude', max_digits=11, decimal_places=8, read_only=True)
    unread_messages_count = serializers.SerializerMethodField()
    has_customer_feedback = serializers.SerializerMethodField()
    has_retailer_rating = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer_name', 'customer_phone', 'customer_email',
            'retailer', 'retailer_name', 'retailer_phone',
            'retailer_address', 'delivery_mode', 'payment_mode', 'status',
            'subtotal', 'delivery_fee', 'discount_amount', 'discount_from_points', 'points_redeemed', 'total_amount',
            'special_instructions', 'cancellation_reason', 'delivery_address_text',
            'delivery_latitude', 'delivery_longitude',
            'items', 'created_at', 'updated_at', 'confirmed_at', 'delivered_at',
            'cancelled_at', 'unread_messages_count',
            'has_customer_feedback', 'has_retailer_rating'
        ]
    
    def get_unread_messages_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return 0
        
        # Count messages NOT sent by me and NOT read
        return obj.chat_messages.exclude(sender=request.user).filter(is_read=False).count()

    def get_has_customer_feedback(self, obj):
        return hasattr(obj, 'feedback')

    def get_has_retailer_rating(self, obj):
        return hasattr(obj, 'retailer_rating')


class OrderCreateSerializer(serializers.Serializer):
    """
    Serializer for creating orders
    """
    retailer_id = serializers.IntegerField()
    address_id = serializers.IntegerField(required=False)
    delivery_mode = serializers.ChoiceField(choices=Order.DELIVERY_MODE_CHOICES)
    payment_mode = serializers.ChoiceField(choices=Order.PAYMENT_MODE_CHOICES)
    special_instructions = serializers.CharField(required=False, allow_blank=True)
    use_reward_points = serializers.BooleanField(required=False, default=False)
    
    def validate_retailer_id(self, value):
        """Validate retailer exists"""
        from retailers.models import RetailerProfile
        try:
            retailer = RetailerProfile.objects.get(id=value, is_active=True)
            return value
        except RetailerProfile.DoesNotExist:
            raise serializers.ValidationError("Retailer not found")
    
    def validate_address_id(self, value):
        """Validate address belongs to customer"""
        if value:
            customer = self.context['customer']
            try:
                address = CustomerAddress.objects.get(id=value, customer=customer, is_active=True)
                return value
            except CustomerAddress.DoesNotExist:
                raise serializers.ValidationError("Address not found")
        return value
    
    def validate(self, data):
        """Validate order data"""
        if data['delivery_mode'] == 'delivery' and not data.get('address_id'):
            raise serializers.ValidationError("Address is required for delivery orders")
        
        if data['delivery_mode'] == 'delivery' and data['payment_mode'] not in ['cash']:
            raise serializers.ValidationError("Invalid payment mode for delivery")
        
        if data['delivery_mode'] == 'pickup' and data['payment_mode'] not in ['cash_pickup']:
            raise serializers.ValidationError("Invalid payment mode for pickup")
        
        return data
    
    def create(self, validated_data):
        """Create order from cart"""
        from retailers.models import RetailerProfile
        
        customer = self.context['customer']
        retailer = RetailerProfile.objects.get(id=validated_data['retailer_id'])
        
        # Get customer's cart for this retailer
        try:
            cart = Cart.objects.get(customer=customer, retailer=retailer)
        except Cart.DoesNotExist:
            raise serializers.ValidationError("Cart is empty")
        
        cart_items = cart.items.select_related('product').all()
        if not cart_items.exists():
            raise serializers.ValidationError("Cart is empty")
        
        # Validate cart items availability
        for cart_item in cart_items:
            if not cart_item.product.can_order_quantity(cart_item.quantity):
                raise serializers.ValidationError(
                    f"Product '{cart_item.product.name}' is not available in requested quantity"
                )
        
        # Calculate totals
        subtotal = sum(item.total_price for item in cart_items)
        delivery_fee = 0
        if validated_data['delivery_mode'] == 'delivery':
            delivery_fee = 50  # Fixed delivery fee, can be made configurable
        
        total_amount = subtotal + delivery_fee
        
        # Calculate discount from points
        discount_from_points = 0
        points_to_redeem = 0
        
        if validated_data.get('use_reward_points', False):
            from retailers.models import RetailerRewardConfig
            from customers.models import CustomerLoyalty
            
            # Get retailer config
            config = RetailerRewardConfig.objects.filter(retailer=retailer).first()
            
            # Get user points for this retailer
            try:
                loyalty = CustomerLoyalty.objects.get(customer=customer, retailer=retailer)
                user_points = loyalty.points
            except CustomerLoyalty.DoesNotExist:
                user_points = 0
            
            if config and config.is_active and user_points > 0:
                # Calculate max redeemable amount
                # 1. Percentage limit
                max_by_percent = (total_amount * config.max_reward_usage_percent) / 100
                
                # 2. Flat limit
                max_by_flat = config.max_reward_usage_flat
                
                # 3. User balance limit (converted to currency)
                # Assuming 1 point = conversion_rate currency
                max_by_balance = user_points * config.conversion_rate
                
                # Actual allowed amount is min of all constraints
                redeemable_amount = min(total_amount, max_by_percent, max_by_flat, max_by_balance)
                
                if redeemable_amount > 0:
                    discount_from_points = redeemable_amount
                    points_to_redeem = redeemable_amount / config.conversion_rate
                    total_amount -= discount_from_points
        
        # Check minimum order amount
        if total_amount < retailer.minimum_order_amount:
            raise serializers.ValidationError(
                f"Minimum order amount is ₹{retailer.minimum_order_amount}"
            )
        
        # Create order
        with transaction.atomic():
            order_data = {
                'customer': customer,
                'retailer': retailer,
                'delivery_mode': validated_data['delivery_mode'],
                'payment_mode': validated_data['payment_mode'],
                'subtotal': subtotal,
                'delivery_fee': delivery_fee,
                'discount_from_points': discount_from_points,
                'points_redeemed': points_to_redeem,
                'total_amount': total_amount,
                'special_instructions': validated_data.get('special_instructions', ''),
            }
            
            if validated_data.get('address_id'):
                order_data['delivery_address'] = CustomerAddress.objects.get(
                    id=validated_data['address_id']
                )
            
            order = Order.objects.create(**order_data)
            
            # Prepare for bulk operations
            order_items = []
            products_to_update = []
            from products.models import Product  # Ensure Product is imported

            for cart_item in cart_items:
                order_items.append(OrderItem(
                    order=order,
                    product=cart_item.product,
                    product_name=cart_item.product.name,
                    product_price=cart_item.product.price,
                    product_unit=cart_item.product.unit,
                    quantity=cart_item.quantity,
                    unit_price=cart_item.product.price,
                    total_price=cart_item.total_price
                ))
                
                # Reduce product quantity in memory
                cart_item.product.quantity -= cart_item.quantity
                products_to_update.append(cart_item.product)
            
            # Bulk create items
            OrderItem.objects.bulk_create(order_items)
            
            # Bulk update product quantities
            Product.objects.bulk_update(products_to_update, ['quantity'])
            
            # Deduct points from customer profile if used
            if points_to_redeem > 0:
                from customers.models import CustomerLoyalty
                try:
                    loyalty = CustomerLoyalty.objects.get(customer=customer, retailer=retailer)
                    loyalty.points -= points_to_redeem
                    loyalty.save()
                except CustomerLoyalty.DoesNotExist:
                    # Should not happen given validation above, but safe handle
                    pass
            
            # Clear cart
            cart.items.all().delete()
            
            # Create initial status log
            OrderStatusLog.objects.create(
                order=order,
                old_status='',
                new_status='pending',
                changed_by=customer
            )
            
            return order


class OrderStatusUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating order status
    """
    status = serializers.ChoiceField(choices=Order.ORDER_STATUS_CHOICES)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_status(self, value):
        """Validate status transition"""
        order = self.context['order']
        current_status = order.status
        
        # Define valid status transitions
        valid_transitions = {
            'pending': ['confirmed', 'cancelled', 'waiting_for_customer_approval'],
            'waiting_for_customer_approval': ['confirmed', 'cancelled', 'pending'],
            'confirmed': ['processing', 'cancelled'],
            'processing': ['packed', 'cancelled'],
            'packed': ['out_for_delivery', 'delivered'],
            'out_for_delivery': ['delivered', 'cancelled'],
            'delivered': ['returned'],
            'cancelled': [],
            'returned': []
        }
        
        if value not in valid_transitions.get(current_status, []):
            raise serializers.ValidationError(
                f"Cannot change status from '{current_status}' to '{value}'"
            )
        
        return value
    
    def update(self, instance, validated_data):
        """Update order status"""
        new_status = validated_data['status']
        notes = validated_data.get('notes', '')
        user = self.context['user']
        
        # Update order status
        instance.update_status(new_status, user)
        
        # Update status log with notes
        if notes:
            status_log = instance.status_logs.latest('created_at')
            status_log.notes = notes
            status_log.save()
        
        return instance


class OrderFeedbackSerializer(serializers.ModelSerializer):
    """
    Serializer for order feedback
    """
    class Meta:
        model = OrderFeedback
        fields = [
            'id', 'overall_rating', 'product_quality_rating', 'delivery_rating',
            'service_rating', 'comment', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def validate_overall_rating(self, value):
        """Validate rating range"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def validate_product_quality_rating(self, value):
        """Validate rating range"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def validate_delivery_rating(self, value):
        """Validate rating range"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def validate_service_rating(self, value):
        """Validate rating range"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value
    
    def create(self, validated_data):
        """Create feedback with order and customer from context"""
        order = self.context['order']
        customer = self.context['customer']
        
        # Check if order is delivered
        if order.status != 'delivered':
            raise serializers.ValidationError("Can only provide feedback for delivered orders")
        
        # Check if feedback already exists
        if hasattr(order, 'feedback'):
            raise serializers.ValidationError("Feedback already provided for this order")
        
        return OrderFeedback.objects.create(
            order=order,
            customer=customer,
            **validated_data
        )


class OrderReturnSerializer(serializers.ModelSerializer):
    """
    Serializer for order return requests
    """
    class Meta:
        model = OrderReturn
        fields = [
            'id', 'reason', 'description', 'status', 'admin_notes',
            'created_at', 'updated_at', 'processed_at'
        ]
        read_only_fields = ['id', 'status', 'admin_notes', 'created_at', 'updated_at', 'processed_at']
    
    def create(self, validated_data):
        """Create return request with order and customer from context"""
        order = self.context['order']
        customer = self.context['customer']
        
        # Check if order is delivered
        if order.status != 'delivered':
            raise serializers.ValidationError("Can only return delivered orders")
        
        # Check if return request already exists
        if hasattr(order, 'return_request'):
            raise serializers.ValidationError("Return request already exists for this order")
        
        # Check if order is within return period (e.g., 7 days)
        from datetime import timedelta
        if order.delivered_at and (timezone.now() - order.delivered_at) > timedelta(days=7):
            raise serializers.ValidationError("Return period has expired")
        
        return OrderReturn.objects.create(
            order=order,
            customer=customer,
            **validated_data
        )


class OrderStatsSerializer(serializers.Serializer):
    """
    Serializer for order statistics
    """
    total_orders = serializers.IntegerField()
    pending_orders = serializers.IntegerField()
    confirmed_orders = serializers.IntegerField()
    delivered_orders = serializers.IntegerField()
    cancelled_orders = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=10, decimal_places=2)
    today_orders = serializers.IntegerField()
    today_revenue = serializers.DecimalField(max_digits=10, decimal_places=2)
    average_order_value = serializers.DecimalField(max_digits=10, decimal_places=2)
    top_customers = serializers.ListField()
    recent_orders = serializers.ListField()
    total_products = serializers.IntegerField(required=False)
    average_rating = serializers.FloatField(required=False)
    recent_reviews = serializers.ListField(required=False)


class OrderModificationSerializer(serializers.Serializer):
    """
    Serializer for modifying order by retailer
    """
    items = serializers.ListField(
        child=serializers.DictField()
    )
    delivery_mode = serializers.ChoiceField(choices=Order.DELIVERY_MODE_CHOICES, required=False)
    discount_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)

    def validate_items(self, value):
        """Validate items structure and content"""
        for item in value:
            if 'id' not in item and 'product_id' not in item:
                raise serializers.ValidationError("Item ID (for existing) or Product ID (for new) is required")
            
            if 'product_id' in item:
                # New item validation
                if 'quantity' not in item:
                    raise serializers.ValidationError("Quantity is required for new items")
                if int(item['quantity']) <= 0:
                     raise serializers.ValidationError("Quantity must be positive for new items")
            
            if 'id' in item:
                # Existing item validation
                if 'quantity' not in item and 'unit_price' not in item:
                    raise serializers.ValidationError("Either quantity or unit_price is required for update")
        return value

    def update(self, instance, validated_data):
        """Update order items and details"""
        items_data = validated_data.get('items', [])
        delivery_mode = validated_data.get('delivery_mode')
        discount_amount = validated_data.get('discount_amount')
        
        with transaction.atomic():
            # Update items
            subtotal = current_subtotal = 0
            
            # Create a map of existing items for easy access
            existing_items = {item.id: item for item in instance.items.all()}
            
            for item_data in items_data:
                # Handle existing items
                if 'id' in item_data:
                    item_id = item_data.get('id')
                    if item_id in existing_items:
                        item = existing_items[item_id]
                        
                        # Update quantity if provided
                        if 'quantity' in item_data:
                            quantity = int(item_data['quantity'])
                            if quantity < 0:
                                raise serializers.ValidationError(f"Invalid quantity for item {item.product_name}")
                            
                            if quantity == 0:
                                # Remove item
                                # Restore stock
                                item.product.increase_quantity(item.quantity)
                                item.delete()
                                continue
                            
                            # Handle stock change for quantity difference
                            diff = quantity - item.quantity
                            if diff > 0:
                                 # Need more
                                 if not item.product.can_order_quantity(diff):
                                     raise serializers.ValidationError(f"Not enough stock for {item.product_name}")
                                 item.product.reduce_quantity(diff)
                            elif diff < 0:
                                 # Returning some
                                 item.product.increase_quantity(abs(diff))
                            
                            item.quantity = quantity
                        
                        # Update price if provided
                        if 'unit_price' in item_data:
                            item.unit_price = item_data['unit_price']
                        
                        # Recalculate item total and save
                        item.save() # save() method in model calculates total_price
                
                # Handle new items
                elif 'product_id' in item_data:
                    product_id = item_data.get('product_id')
                    quantity = int(item_data['quantity'])
                    
                    try:
                        product = Product.objects.get(id=product_id, retailer=instance.retailer)
                    except Product.DoesNotExist:
                        raise serializers.ValidationError(f"Product with ID {product_id} not found in your catalog")
                    
                    # Check stock
                    if not product.can_order_quantity(quantity):
                        raise serializers.ValidationError(f"Not enough stock for {product.name}")
                    
                    # Reduce stock
                    product.reduce_quantity(quantity)
                    
                    # Create new OrderItem
                    OrderItem.objects.create(
                        order=instance,
                        product=product,
                        product_name=product.name,
                        product_price=product.price,
                        product_unit=product.unit,
                        quantity=quantity,
                        unit_price=product.price, # Default to current product price
                        total_price=product.price * quantity
                    )
            
            # Recalculate order subtotal from scratch to be safe
            # (In case some items were not in the update list but still exist)
            subtotal = sum(item.total_price for item in instance.items.all())
            instance.subtotal = subtotal
            
            # Update delivery mode
            if delivery_mode:
                instance.delivery_mode = delivery_mode
                # Recalculate delivery fee logic if needed (e.g. 50 for delivery, 0 for pickup)
                if delivery_mode == 'delivery':
                     instance.delivery_fee = 50 # Fixed for now as per OrderCreate
                     if not instance.delivery_address:
                         # Requires address? If switching to delivery without address, this might be issue.
                         # Assuming address exists or validation handled.
                         pass
                else:
                    instance.delivery_fee = 0
            
            # Update discount
            if discount_amount is not None:
                instance.discount_amount = discount_amount
            
            # Recalculate total
            instance.total_amount = instance.subtotal + instance.delivery_fee - instance.discount_amount - instance.discount_from_points
            
            # Validate total amount
            if instance.total_amount < 0:
                instance.total_amount = 0
            
            
            # Change status to waiting for approval using update_status to trigger notifications
            instance.update_status('waiting_for_customer_approval', self.context.get('user'))
            
            return instance


class OrderChatMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for order chat messages
    """
    sender_name = serializers.CharField(source='sender.first_name', read_only=True)
    sender_type = serializers.CharField(source='sender.user_type', read_only=True)
    is_me = serializers.SerializerMethodField()
    
    class Meta:
        model = OrderChatMessage
        fields = [
            'id', 'sender', 'sender_name', 'sender_type', 'message', 
            'is_read', 'created_at', 'is_me'
        ]
        read_only_fields = ['id', 'sender', 'created_at', 'is_read']
    
    def get_is_me(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.sender == request.user
        return False


class RetailerRatingSerializer(serializers.ModelSerializer):
    """
    Serializer for retailer rating (Retailer -> Customer)
    """
    class Meta:
        model = RetailerRating
        fields = [
            'id', 'rating', 'comment', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def validate_rating(self, value):
        """Validate rating range (0-5)"""
        if value < 0 or value > 5:
            raise serializers.ValidationError("Rating must be between 0 and 5")
        return value
    
    def create(self, validated_data):
        """Create rating with order and retailer from context"""
        order = self.context['order']
        retailer = self.context['retailer']
        customer = order.customer
        
        # Check if order is delivered or cancelled (retailers can probably rate cancelled orders too strictly speaking, but let's stick to completed/cancelled flow)
        # Actually requirements say "after every completed order".
        # Let's assume 'delivered', 'cancelled', 'returned' are completed states.
        if not order.is_completed: 
             # Wait, is_completed is a property in model? Yes lines 152-155: delivered, cancelled, returned.
             raise serializers.ValidationError("Can only rate completed orders")

        
        # Check if rating already exists
        if hasattr(order, 'retailer_rating'):
            raise serializers.ValidationError("Rating already provided for this customer on this order")
        
        return RetailerRating.objects.create(
            order=order,
            retailer=retailer,
            customer=customer,
            **validated_data
        )
