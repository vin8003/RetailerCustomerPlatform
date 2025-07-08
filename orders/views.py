from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Sum, Count, Avg
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
import logging

from .models import Order, OrderItem, OrderStatusLog, OrderFeedback, OrderReturn
from .serializers import (
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer,
    OrderStatusUpdateSerializer, OrderFeedbackSerializer, OrderReturnSerializer,
    OrderStatsSerializer
)
from retailers.models import RetailerProfile
from customers.models import CustomerAddress

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
        
        serializer = OrderCreateSerializer(
            data=request.data,
            context={'customer': request.user}
        )
        
        if serializer.is_valid():
            order = serializer.save()
            response_serializer = OrderDetailSerializer(order)
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
        
        if user.user_type == 'customer':
            orders = Order.objects.filter(
                customer=user,
                status__in=['pending', 'confirmed', 'processing', 'packed', 'out_for_delivery']
            ).order_by('-created_at')
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                orders = Order.objects.filter(
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
        
        if user.user_type == 'customer':
            orders = Order.objects.filter(
                customer=user,
                status__in=['delivered', 'cancelled', 'returned']
            ).order_by('-created_at')
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                orders = Order.objects.filter(
                    retailer=retailer,
                    status__in=['delivered', 'cancelled', 'returned']
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
        
        serializer = OrderDetailSerializer(order)
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
            response_serializer = OrderDetailSerializer(order)
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
        
        logger.info(f"Order cancelled: {order.order_number} by {user.username}")
        
        serializer = OrderDetailSerializer(order)
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
        today = timezone.now().date()
        
        # Calculate statistics
        total_orders = orders.count()
        pending_orders = orders.filter(status='pending').count()
        confirmed_orders = orders.filter(status='confirmed').count()
        delivered_orders = orders.filter(status='delivered').count()
        cancelled_orders = orders.filter(status='cancelled').count()
        
        # Revenue calculations
        total_revenue = orders.filter(status='delivered').aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        
        today_orders = orders.filter(created_at__date=today).count()
        today_revenue = orders.filter(
            created_at__date=today,
            status='delivered'
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        # Average order value
        avg_order_value = orders.filter(status='delivered').aggregate(
            avg=Avg('total_amount')
        )['avg'] or 0
        
        # Top customers
        top_customers = orders.filter(status='delivered').values(
            'customer__first_name', 'customer__id'
        ).annotate(
            order_count=Count('id'),
            total_spent=Sum('total_amount')
        ).order_by('-total_spent')[:5]
        
        # Recent orders
        recent_orders = orders.order_by('-created_at')[:5]
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
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'confirmed_orders': confirmed_orders,
            'delivered_orders': delivered_orders,
            'cancelled_orders': cancelled_orders,
            'total_revenue': total_revenue,
            'today_orders': today_orders,
            'today_revenue': today_revenue,
            'average_order_value': avg_order_value,
            'top_customers': list(top_customers),
            'recent_orders': recent_orders_data
        }
        
        serializer = OrderStatsSerializer(stats_data)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting order stats: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
