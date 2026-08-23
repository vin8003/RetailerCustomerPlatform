from decimal import Decimal
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Sum, Count, Avg, F
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils import timezone
from datetime import timedelta
import logging
import re
from common.error_utils import format_exception

from .models import Order, OrderItem, OrderStatusLog, OrderFeedback, OrderReturn, OrderChatMessage, RetailerRating
from .status_filters import apply_order_status_filter
from .serializers import (
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer,
    OrderStatusUpdateSerializer, OrderFeedbackSerializer, OrderReturnSerializer,
    OrderStatsSerializer, OrderModificationSerializer, OrderChatMessageSerializer,
    RetailerRatingSerializer
)
from retailers.models import RetailerProfile, RetailerReview, RetailerRewardConfig
from retailers.serializers import RetailerReviewSerializer
from customers.models import CustomerAddress, CustomerLoyalty
from django.db.models import Exists, OuterRef, Prefetch
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
            # Check for blacklist
            from retailers.models import RetailerBlacklist, RetailerProfile
            retailer_id = request.data.get('retailer_id')
            if retailer_id:
                try:
                    retailer = RetailerProfile.objects.get(id=retailer_id)
                    if RetailerBlacklist.objects.filter(retailer=retailer, customer=request.user).exists():
                        return Response(
                            {'error': 'You are blacklisted by this retailer and cannot place orders.'},
                            status=status.HTTP_403_FORBIDDEN
                        )
                except RetailerProfile.DoesNotExist:
                     pass # Serializer will handle this

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
            {'error': format_exception(e)}, 
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
        # Annotate has_feedback and has_rating efficiently
        
        has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
        has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))
        
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(
            items_count_annotated=Count('items'),
            has_feedback_annotated=has_feedback_subquery,
            has_rating_annotated=has_rating_subquery
        )

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
        orders = apply_order_status_filter(orders, request.query_params.get('status'))
        
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
            {'error': format_exception(e)}, 
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
        has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
        has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))
        
        # Base queryset with optimizations
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(
            items_count_annotated=Count('items'),
            has_feedback_annotated=has_feedback_subquery,
            has_rating_annotated=has_rating_subquery
        )

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
        
        # Apply filters (KAN-77: Returned includes sales-return rows)
        orders = apply_order_status_filter(orders, request.query_params.get('status'))
        
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
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
