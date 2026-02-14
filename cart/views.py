from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import prefetch_related_objects
import logging

from .models import Cart, CartItem, CartHistory
from .serializers import (
    CartSerializer, CartItemSerializer, AddToCartSerializer,
    UpdateCartItemSerializer, CartSummarySerializer
)
from products.models import Product
from retailers.models import RetailerProfile

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_cart(request):
    """
    Get current cart for authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access cart'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get retailer_id from query params to get specific cart
        retailer_id = request.query_params.get('retailer_id')
        
        if retailer_id:
            try:
                retailer = RetailerProfile.objects.get(id=retailer_id, is_active=True)
                cart, created = Cart.objects.get_or_create(
                    customer=request.user,
                    retailer=retailer
                )
                prefetch_related_objects([cart], 'items__product', 'retailer')
                serializer = CartSerializer(cart)
                data = serializer.data
                
                # Calculate Offers
                from offers.engine import OfferEngine
                engine = OfferEngine()
                
                # Pass cart items directly (Engine expects objects with product/quantity attrs)
                # Pass cart items directly (Engine expects objects with product/quantity attrs)
                # Engine needs product category/brand for rules
                cart_items = cart.items.select_related('product', 'product__category', 'product__brand').all()

                offer_results = engine.calculate_offers(cart_items, retailer)
                
                # Merge offer results into response
                data['subtotal'] = offer_results['subtotal']
                data['discounted_total'] = offer_results['discounted_total']
                data['total_savings'] = offer_results['total_savings']
                data['applied_offers'] = offer_results['applied_offers']
                data['item_discounts'] = offer_results['item_discounts']
                
                # Calculate potential cashback (From Offers Engine)
                potential_points = offer_results.get('total_points', 0)
                    
                data['potential_points'] = potential_points
                
                return Response(data, status=status.HTTP_200_OK)
            except RetailerProfile.DoesNotExist:
                return Response(
                    {'error': 'Retailer not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            # Get all carts for customer
            carts = Cart.objects.filter(customer=request.user).select_related('retailer').prefetch_related('items__product')
            serializer = CartSerializer(carts, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting cart: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_to_cart(request):
    """
    Add item to cart
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can add items to cart'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = AddToCartSerializer(
            data=request.data,
            context={'customer': request.user}
        )
        
        if serializer.is_valid():
            cart_item = serializer.save()
            
            # Auto-add free items for Same Product BXGY (User Request: "1 add krne pe 2 auto add ho")
            try:
                from offers.models import Offer
                from django.utils import timezone
                from django.db.models import Q
                
                now = timezone.now()
                # Find active Same Product BXGY offers
                active_offers = Offer.objects.filter(
                    retailer=cart_item.cart.retailer,
                    offer_type='bxgy',
                    bxgy_strategy='same_product',
                    is_active=True,
                    start_date__lte=now
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=now)
                ).order_by('-priority')
                
                product = cart_item.product
                
                for offer in active_offers:
                    targets = offer.targets.all()
                    if not targets:
                        continue
                        
                    is_match = False
                    is_excluded = False
                    
                    for target in targets:
                        if target.is_excluded:
                            if target.target_type == 'product' and target.product_id == product.id:
                                is_excluded = True
                            elif target.target_type == 'category' and target.category_id == product.category_id:
                                is_excluded = True
                            elif target.target_type == 'brand' and target.brand_id == product.brand_id:
                                is_excluded = True
                        else:
                            if target.target_type == 'all_products':
                                is_match = True
                            elif target.target_type == 'product' and target.product_id == product.id:
                                is_match = True
                            elif target.target_type == 'category' and target.category_id == product.category_id:
                                is_match = True
                            elif target.target_type == 'brand' and target.brand_id == product.brand_id:
                                is_match = True
                    
                    if is_match and not is_excluded:
                        # Logic: If item quantity equals Buy Quantity, add Get Quantity
                        # e.g., Buy 1 Get 2. If Qty matches 1, make it 3.
                        if offer.buy_quantity and offer.get_quantity:
                            if cart_item.quantity == offer.buy_quantity:
                                cart_item.quantity += offer.get_quantity
                                cart_item.save()
                                logger.info(f"Auto-added {offer.get_quantity} free items for offer {offer.name} to product {product.name}")
                                break # Apply top priority offer only
            
            except Exception as e:
                logger.error(f"Error processing auto-add offers: {str(e)}")

            # Return updated cart
            cart = cart_item.cart
            cart_serializer = CartSerializer(cart)
            
            logger.info(f"Item added to cart: {cart_item.product.name} by {request.user.username}")
            return Response(cart_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error adding to cart: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_cart_item(request, item_id):
    """
    Update cart item quantity
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can update cart items'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        cart_item = get_object_or_404(
            CartItem, 
            id=item_id, 
            cart__customer=request.user
        )
        
        serializer = UpdateCartItemSerializer(
            cart_item,
            data=request.data,
            context={'cart_item': cart_item}
        )
        
        if serializer.is_valid():
            cart_item = serializer.save()
            
            # Return updated cart
            cart = cart_item.cart
            cart_serializer = CartSerializer(cart)
            
            logger.info(f"Cart item updated: {cart_item.product.name} by {request.user.username}")
            return Response(cart_serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error updating cart item: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def remove_cart_item(request, item_id):
    """
    Remove item from cart
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can remove cart items'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        cart_item = get_object_or_404(
            CartItem, 
            id=item_id, 
            cart__customer=request.user
        )
        
        cart = cart_item.cart
        product = cart_item.product
        
        # Log cart history
        CartHistory.objects.create(
            customer=request.user,
            retailer=cart.retailer,
            product=product,
            action='remove',
            quantity=cart_item.quantity,
            price=product.price
        )
        
        cart_item.delete()
        
        # Return updated cart
        cart.refresh_from_db()
        cart_serializer = CartSerializer(cart)
        
        logger.info(f"Item removed from cart: {product.name} by {request.user.username}")
        return Response(cart_serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error removing cart item: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def clear_cart(request):
    """
    Clear entire cart for a retailer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can clear cart'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        retailer_id = request.data.get('retailer_id')
        
        if not retailer_id:
            return Response(
                {'error': 'Retailer ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            retailer = RetailerProfile.objects.get(id=retailer_id, is_active=True)
            cart = Cart.objects.get(customer=request.user, retailer=retailer)
            
            # Log cart history
            CartHistory.objects.create(
                customer=request.user,
                retailer=retailer,
                action='clear'
            )
            
            cart.clear()
            
            cart_serializer = CartSerializer(cart)
            logger.info(f"Cart cleared for retailer: {retailer.shop_name} by {request.user.username}")
            return Response(cart_serializer.data, status=status.HTTP_200_OK)
            
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Cart.DoesNotExist:
            return Response(
                {'error': 'Cart not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    except Exception as e:
        logger.error(f"Error clearing cart: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_cart_summary(request):
    """
    Get cart summary for checkout
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access cart summary'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        retailer_id = request.query_params.get('retailer_id')
        
        if not retailer_id:
            return Response(
                {'error': 'Retailer ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            retailer = RetailerProfile.objects.get(id=retailer_id, is_active=True)
            cart = Cart.objects.prefetch_related('items__product').get(customer=request.user, retailer=retailer)
            
            # Calculate summary
            total_items = cart.total_items
            total_amount = cart.total_amount
            minimum_order_amount = retailer.minimum_order_amount
            
            can_checkout = total_amount >= minimum_order_amount and not cart.is_empty
            checkout_message = ""
            
            if cart.is_empty:
                checkout_message = "Your cart is empty"
            elif total_amount < minimum_order_amount:
                checkout_message = f"Minimum order amount is ₹{minimum_order_amount}"
            else:
                checkout_message = "Ready to checkout"
            
            # Check if all items are available
            unavailable_items = []
            for item in cart.items.all():
                if not item.is_available:
                    unavailable_items.append(item.product.name)
            
            if unavailable_items:
                can_checkout = False
                checkout_message = f"Some items are unavailable: {', '.join(unavailable_items)}"
            
            summary_data = {
                'total_items': total_items,
                'total_amount': total_amount,
                'retailer_name': retailer.shop_name,
                'retailer_id': retailer.id,
                'minimum_order_amount': minimum_order_amount,
                'can_checkout': can_checkout,
                'checkout_message': checkout_message
            }
            
            serializer = CartSummarySerializer(summary_data)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Cart.DoesNotExist:
            return Response(
                {'error': 'Cart not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    except Exception as e:
        logger.error(f"Error getting cart summary: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def validate_cart(request):
    """
    Validate cart items before checkout
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can validate cart'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        retailer_id = request.data.get('retailer_id')
        
        if not retailer_id:
            return Response(
                {'error': 'Retailer ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            retailer = RetailerProfile.objects.get(id=retailer_id, is_active=True)
            cart = Cart.objects.prefetch_related('items__product').get(customer=request.user, retailer=retailer)
            
            if cart.is_empty:
                return Response(
                    {'valid': False, 'message': 'Cart is empty'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate each item
            validation_errors = []
            
            for item in cart.items.all():
                if not item.product.is_available or not item.product.is_active:
                    validation_errors.append(f"{item.product.name} is no longer available")
                elif item.quantity > item.product.quantity:
                    validation_errors.append(
                        f"{item.product.name} - only {item.product.quantity} items available"
                    )
                else:
                    # Check minimum and maximum order quantities
                    if item.quantity < item.product.minimum_order_quantity:
                        validation_errors.append(
                            f"{item.product.name} - minimum order quantity is {item.product.minimum_order_quantity}"
                        )
                    
                    if item.product.maximum_order_quantity and item.quantity > item.product.maximum_order_quantity:
                        validation_errors.append(
                            f"{item.product.name} - maximum order quantity is {item.product.maximum_order_quantity}"
                        )
            
            # Check minimum order amount
            if cart.total_amount < retailer.minimum_order_amount:
                validation_errors.append(
                    f"Minimum order amount is ₹{retailer.minimum_order_amount}"
                )
            
            if validation_errors:
                return Response(
                    {'valid': False, 'errors': validation_errors}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            return Response(
                {'valid': True, 'message': 'Cart is valid for checkout'}, 
                status=status.HTTP_200_OK
            )
            
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Cart.DoesNotExist:
            return Response(
                {'error': 'Cart not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    except Exception as e:
        logger.error(f"Error validating cart: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_cart_count(request):
    """
    Get total cart count for authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access cart count'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get total items across all carts
        total_items = 0
        carts = Cart.objects.filter(customer=request.user)
        
        for cart in carts:
            total_items += cart.total_items
        
        return Response(
            {'total_items': total_items}, 
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        logger.error(f"Error getting cart count: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
