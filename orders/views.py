from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Sum, Count, Avg
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils import timezone
from datetime import timedelta
import logging

from .models import Order, OrderItem, OrderStatusLog, OrderFeedback, OrderReturn, OrderChatMessage
from .serializers import (
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer,
    OrderStatusUpdateSerializer, OrderFeedbackSerializer, OrderReturnSerializer,
    OrderStatsSerializer, OrderModificationSerializer, OrderChatMessageSerializer
)
from retailers.models import RetailerProfile, RetailerReview
from retailers.serializers import RetailerReviewSerializer
from customers.models import CustomerAddress
from common.notifications import send_push_notification

logger = logging.getLogger(__name__)


class OrderPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def place_order(request):
    """
    Place a new order from cart
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can place orders'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not request.user.is_phone_verified:
            return Response(
                {'error': 'Please verify your phone number to place orders.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = OrderCreateSerializer(
            data=request.data,
            context={'customer': request.user}
        )
        
        if serializer.is_valid():
            order = serializer.save()
            
            # Notify Retailer
            if order.retailer and order.retailer.user:
                send_push_notification(
                    user=order.retailer.user,
                    title="New Order Received!",
                    message=f"Order #{order.order_number} has been placed by {request.user.get_full_name() or request.user.username}.",
                    data={
                        'type': 'new_order',
                        'order_id': str(order.id)
                    }
                )
                
                # Silent refresh for Retailer Dashboard
                from common.notifications import send_silent_update
                send_silent_update(
                    user=order.retailer.user,
                    event_type='order_refresh',
                    data={'order_id': str(order.id)}
                )

            response_serializer = OrderDetailSerializer(order, context={'request': request})
            logger.info(f"Order placed: {order.order_number} by {request.user.username}")
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_current_orders(request):
    """
    Get current orders for authenticated user
    """
    try:
        user = request.user
        
        # Base queryset with optimizations
        # We annotate items_count to avoid N+1 count queries
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(items_count_annotated=Count('items'))

        if user.user_type == 'customer':
            orders = base_qs.filter(
                customer=user,
                status__in=['pending', 'confirmed', 'processing', 'packed', 'out_for_delivery']
            ).order_by('-created_at')
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                orders = base_qs.filter(
                    retailer=retailer,
                    status__in=['pending', 'confirmed', 'processing', 'packed', 'out_for_delivery']
                ).order_by('-created_at')
            except RetailerProfile.DoesNotExist:
                return Response(
                    {'error': 'Retailer profile not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {'error': 'Invalid user type'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Apply filters
        status_filter = request.query_params.get('status')
        if status_filter:
            orders = orders.filter(status=status_filter)
        
        # Search by order number
        search = request.query_params.get('search')
        if search:
            orders = orders.filter(order_number__icontains=search)
        
        # Pagination
        paginator = OrderPagination()
        page = paginator.paginate_queryset(orders, request)
        
        if page is not None:
            serializer = OrderListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderListSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting current orders: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_history(request):
    """
    Get order history for authenticated user
    """
    try:
        user = request.user
        
        # Base queryset with optimizations
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(items_count_annotated=Count('items'))

        if user.user_type == 'customer':
            orders = base_qs.filter(
                customer=user
            ).order_by('-created_at')
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                orders = base_qs.filter(
                    retailer=retailer
                ).order_by('-created_at')
            except RetailerProfile.DoesNotExist:
                return Response(
                    {'error': 'Retailer profile not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {'error': 'Invalid user type'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Apply filters
        status_filter = request.query_params.get('status')
        if status_filter:
            orders = orders.filter(status=status_filter)
        
        # Date range filtering
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if start_date:
            try:
                start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
                orders = orders.filter(created_at__date__gte=start_date)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
                orders = orders.filter(created_at__date__lte=end_date)
            except ValueError:
                pass
        
        # Search by order number
        search = request.query_params.get('search')
        if search:
            orders = orders.filter(order_number__icontains=search)
        
        # Pagination
        paginator = OrderPagination()
        page = paginator.paginate_queryset(orders, request)
        
        if page is not None:
            serializer = OrderListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderListSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting order history: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_detail(request, order_id):
    """
    Get order detail for authenticated user
    """
    try:
        user = request.user
        
        # Optimize queryset for detail view
        qs = Order.objects.select_related(
            'retailer', 
            'customer', 
            'delivery_address'
        ).prefetch_related(
            'items',
            'items__product'
        )

        if user.user_type == 'customer':
            order = get_object_or_404(qs, id=order_id, customer=user)
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                order = get_object_or_404(qs, id=order_id, retailer=retailer)
            except RetailerProfile.DoesNotExist:
                return Response(
                    {'error': 'Retailer profile not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {'error': 'Invalid user type'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        # Optimization: Check if data has changed
        last_updated = request.query_params.get('last_updated')
        if last_updated:
            # Convert order.updated_at to string format used by serializer
            # or simply compare timestamps if client sends iso format
            current_updated = order.updated_at.isoformat().replace('+00:00', 'Z')
            
            # Simple check - if the passed timestamp matches current, return 304
            # Note: exact string matching depends on client carrying over the exact string
            # We'll try to match broadly or use Parse
            if last_updated == current_updated or last_updated == order.updated_at.isoformat():
                return Response(status=status.HTTP_304_NOT_MODIFIED)
        
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting order detail: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_order_status(request, order_id):
    """
    Update order status - only for retailers
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can update order status'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
            order = get_object_or_404(Order, id=order_id, retailer=retailer)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = OrderStatusUpdateSerializer(
            order,
            data=request.data,
            context={'order': order, 'user': request.user}
        )
        
        if serializer.is_valid():
            order = serializer.save()
            response_serializer = OrderDetailSerializer(order, context={'request': request})
            logger.info(f"Order status updated: {order.order_number} to {order.status}")
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error updating order status: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cancel_order(request, order_id):
    """
    Cancel order - for customers and retailers
    """
    try:
        user = request.user
        
        if user.user_type == 'customer':
            order = get_object_or_404(Order, id=order_id, customer=user)
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                order = get_object_or_404(Order, id=order_id, retailer=retailer)
            except RetailerProfile.DoesNotExist:
                return Response(
                    {'error': 'Retailer profile not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {'error': 'Invalid user type'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if order can be cancelled
        if not order.can_be_cancelled:
            return Response(
                {'error': 'Order cannot be cancelled'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get cancellation reason
        reason = request.data.get('reason', '')
        
        # Cancel order
        order.update_status('cancelled', user)
        order.cancellation_reason = reason
        order.save()
        
        # Restore product quantities
        for item in order.items.all():
            item.product.increase_quantity(item.quantity)
            
        # Refund loyalty points if used (Handled in update_status but ensured here logic is consistent)
        # Actually update_status('cancelled') already calls refund logic in models.py.
        # So we don't need to duplicate it here, BUT we should verify that update_status IS called correctly.
        # It is called above.
        
        logger.info(f"Order cancelled: {order.order_number} by {user.username}")
        
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error cancelling order: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_order_feedback(request, order_id):
    """
    Create feedback for an order - only for customers
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can provide feedback'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        
        serializer = OrderFeedbackSerializer(
            data=request.data,
            context={'order': order, 'customer': request.user}
        )
        
        if serializer.is_valid():
            feedback = serializer.save()
            logger.info(f"Feedback created for order: {order.order_number}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error creating order feedback: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_return_request(request, order_id):
    """
    Create return request for an order - only for customers
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can create return requests'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        
        serializer = OrderReturnSerializer(
            data=request.data,
            context={'order': order, 'customer': request.user}
        )
        
        if serializer.is_valid():
            return_request = serializer.save()
            logger.info(f"Return request created for order: {order.order_number}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error creating return request: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_stats(request):
    """
    Get order statistics - only for retailers
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access order stats'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        orders = Order.objects.filter(retailer=retailer)
        from products.models import Product
        total_products = Product.objects.filter(retailer=retailer).count()
        today = timezone.now().date()
        
        # Calculate statistics with optimized aggregation
        stats = orders.aggregate(
            total_orders=Count('id'),
            pending_orders=Count('id', filter=Q(status='pending')),
            confirmed_orders=Count('id', filter=Q(status='confirmed')),
            delivered_orders=Count('id', filter=Q(status='delivered')),
            cancelled_orders=Count('id', filter=Q(status='cancelled')),
            total_revenue=Sum('total_amount', filter=Q(status='delivered')),
            avg_order_value=Avg('total_amount', filter=Q(status='delivered'))
        )
        
        today_stats = orders.filter(created_at__date=today).aggregate(
            today_orders=Count('id'),
            today_revenue=Sum('total_amount', filter=Q(status='delivered'))
        )
        
        # Top customers
        top_customers = orders.filter(status='delivered').values(
            'customer__first_name', 'customer__id'
        ).annotate(
            order_count=Count('id'),
            total_spent=Sum('total_amount')
        ).order_by('-total_spent')[:5]
        
        # Recent orders
        recent_orders = orders.select_related('customer').order_by('-created_at')[:5]
        recent_orders_data = []
        for order in recent_orders:
            recent_orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'customer_name': order.customer.first_name,
                'total_amount': order.total_amount,
                'status': order.status,
                'created_at': order.created_at
            })
        
        stats_data = {
            'total_orders': stats['total_orders'] or 0,
            'pending_orders': stats['pending_orders'] or 0,
            'confirmed_orders': stats['confirmed_orders'] or 0,
            'delivered_orders': stats['delivered_orders'] or 0,
            'cancelled_orders': stats['cancelled_orders'] or 0,
            'total_revenue': stats['total_revenue'] or 0,
            'today_orders': today_stats['today_orders'] or 0,
            'today_revenue': today_stats['today_revenue'] or 0,
            'average_order_value': stats['avg_order_value'] or 0,
            'top_customers': list(top_customers),
            'recent_orders': recent_orders_data,
            'total_products': total_products,
            'average_rating': float(retailer.average_rating),
            'recent_reviews': RetailerReviewSerializer(
                RetailerReview.objects.filter(retailer=retailer).order_by('-created_at')[:5],
                many=True
            ).data
        }
        
        serializer = OrderStatsSerializer(stats_data)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def modify_order(request, order_id):
    """
    Modify order - only for retailers
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can modify orders'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
            order = get_object_or_404(Order, id=order_id, retailer=retailer)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        if order.status != 'pending':
            return Response(
                {'error': 'Only pending orders can be modified'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = OrderModificationSerializer(
            order,
            data=request.data,
            context={'user': request.user}
        )
        
        if serializer.is_valid():
            order = serializer.save()
            
            # Recalculate points discount if points were used
            if order.points_redeemed > 0:
                from retailers.models import RetailerRewardConfig
                from customers.models import CustomerLoyalty
                
                try:
                    config = RetailerRewardConfig.objects.filter(retailer=retailer).first()
                    loyalty = CustomerLoyalty.objects.get(customer=order.customer, retailer=retailer)
                    
                    if config and config.is_active:
                        # Calculate total BEFORE points discount is applied
                        # We calculate from components because total_amount might be capped at 0
                        total_before_points = max(0, order.subtotal + order.delivery_fee - (order.discount_amount or 0))

                        # Calculate max allowed discount for new total
                        # 1. Percentage limit on total_before_points
                        max_by_percent = (total_before_points * config.max_reward_usage_percent) / 100
                        
                        # 2. Flat limit
                        max_by_flat = config.max_reward_usage_flat
                        
                        # 3. Current redeemed points value (the user "paid" this much in points initially)
                        # We don't want to use MORE points than initially redeemed, only LESS if the total dropped
                        current_points_value = order.points_redeemed * config.conversion_rate
                        
                        # New max redeemable amount
                        redeemable_amount = min(total_before_points, max_by_percent, max_by_flat, current_points_value)
                        
                        if redeemable_amount < current_points_value:
                            # Discount needs to be reduced
                            diff_value = current_points_value - redeemable_amount
                            points_to_refund = diff_value / config.conversion_rate
                            
                            # Update order
                            # New discount is redeemable_amount.
                            # We need to set total_amount = total_before_points - new_discount.
                            
                            order.discount_from_points = redeemable_amount
                            order.points_redeemed -= points_to_refund
                            order.total_amount = total_before_points - redeemable_amount
                            order.save()
                            
                            # Refund points to customer
                            loyalty.points += points_to_refund
                            loyalty.save()
                            
                            logger.info(f"Points adjusted for order {order.order_number}: Refunded {points_to_refund} points")

                except Exception as e:
                    logger.error(f"Error adjusting points for modified order: {str(e)}")
            
            response_serializer = OrderDetailSerializer(order)
            logger.info(f"Order modified: {order.order_number} by retailer")
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error modifying order: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def confirm_modification(request, order_id):
    """
    Confirm or reject order modification - only for customers
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can confirm modifications'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        
        if order.status != 'waiting_for_customer_approval':
            return Response(
                {'error': 'Order is not waiting for approval'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        action = request.data.get('action')
        if action not in ['accept', 'reject']:
            return Response(
                {'error': 'Invalid action. Must be accept or reject'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if action == 'accept':
            order.update_status('confirmed', request.user)
            message = 'Order modification accepted'
        else:
            order.cancellation_reason = 'Customer rejected retailer modifications'
            order.update_status('cancelled', request.user)
            order.save()

            # Note: update_status handles point refunds if points were redeemed.
            # But confirm_modification rejection also implies cancelling the mod proposal.
            # However, since we updated the order IN PLACE in modify_order, the order is effectively
            # "Cancelled" with the NEW values. This is fine. The refund will be based on 
            # the current order.points_redeemed.
            
            # Restore stock for items
            for item in order.items.all():
                item.product.increase_quantity(item.quantity)
            
            message = 'Order modification rejected'
        
        logger.info(f"{message}: {order.order_number}")
        
        serializer = OrderDetailSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error confirming modification: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_chat(request, order_id):
    """
    Get chat messages for an order
    """
    try:
        user = request.user
        
        if user.user_type == 'customer':
            order = get_object_or_404(Order, id=order_id, customer=user)
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                order = get_object_or_404(Order, id=order_id, retailer=retailer)
            except RetailerProfile.DoesNotExist:
                return Response({'error': 'Retailer profile not found'}, status=404)
        else:
            return Response({'error': 'Invalid user type'}, status=403)
            
        messages = order.chat_messages.all()
        serializer = OrderChatMessageSerializer(messages, many=True, context={'request': request})
        return Response(serializer.data)
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error getting chat: {e}")
        return Response({'error': 'Internal server error'}, status=500)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_order_message(request, order_id):
    """
    Send a chat message
    """
    try:
        user = request.user
        
        if user.user_type == 'customer':
            order = get_object_or_404(Order, id=order_id, customer=user)
            recipient = order.retailer.user
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                order = get_object_or_404(Order, id=order_id, retailer=retailer)
                recipient = order.customer
            except RetailerProfile.DoesNotExist:
                return Response({'error': 'Retailer profile not found'}, status=404)
        else:
            return Response({'error': 'Invalid user type'}, status=403)
            
        message_text = request.data.get('message')
        if not message_text:
            return Response({'error': 'Message cannot be empty'}, status=400)
            
        message = OrderChatMessage.objects.create(
            order=order,
            sender=user,
            message=message_text
        )
        
        # Send notification to recipient
        if recipient:
            send_push_notification(
                user=recipient,
                title=f"Message from {user.first_name or user.username}",
                message=message_text,
                data={
                    'type': 'order_chat',
                    'order_id': str(order.id)
                }
            )
            
        serializer = OrderChatMessageSerializer(message, context={'request': request})
        return Response(serializer.data, status=201)
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return Response({'error': 'Internal server error'}, status=500)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def mark_chat_read(request, order_id):
    """
    Mark all unread messages in this order as read (for the current user)
    """
    try:
        user = request.user
        
        if user.user_type == 'customer':
            order = get_object_or_404(Order, id=order_id, customer=user)
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                order = get_object_or_404(Order, id=order_id, retailer=retailer)
            except RetailerProfile.DoesNotExist:
                return Response({'error': 'Retailer profile not found'}, status=404)
        else:
            return Response({'error': 'Invalid user type'}, status=403)
            
        # Mark all messages NOT sent by me as read
        order.chat_messages.exclude(sender=user).filter(is_read=False).update(is_read=True)
        
        return Response({'status': 'ok'})
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error marking read: {e}")
        return Response({'error': 'Internal server error'}, status=500)
