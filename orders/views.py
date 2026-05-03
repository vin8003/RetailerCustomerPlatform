from decimal import Decimal
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Sum, Count, Avg, F, Value, DecimalField, BooleanField, CharField, DateTimeField, IntegerField, Subquery
from django.db.models.functions import Coalesce
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils import timezone
from datetime import timedelta
import logging
import re
from common.error_utils import format_exception

from .models import Order, OrderItem, OrderStatusLog, OrderFeedback, OrderReturn, OrderChatMessage, RetailerRating
from .projections import OrderProjectionAdapter
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


def _order_queryset_with_relations():
    return Order.objects.select_related(
        'retailer', 'customer', 'customer__customer_profile', 'delivery_address'
    ).prefetch_related(
        'returns',
        'feedback',
        'retailer_rating',
        'applied_offers__offer',
        'items__product',
    )


def _annotated_order_queryset():
    feedback_qs = OrderFeedback.objects.filter(order=OuterRef('pk'))
    order_return_field_names = {field.name for field in OrderReturn._meta.get_fields()}
    if 'refund_amount' in order_return_field_names:
        refund_amount_qs = (
            OrderReturn.objects.filter(order=OuterRef('pk'))
            .values('order')
            .annotate(total_refund=Sum('refund_amount'))
            .values('total_refund')[:1]
        )
        refund_amount_annotation = Coalesce(
            Subquery(refund_amount_qs, output_field=DecimalField(max_digits=10, decimal_places=2)),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        )
    else:
        refund_amount_annotation = Value(
            Decimal('0.00'),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        )
    return _order_queryset_with_relations().annotate(
        items_count_annotated=Count('items', distinct=True),
        refund_amount_annotated=refund_amount_annotation,
        is_returned_annotated=Exists(OrderReturn.objects.filter(order=OuterRef('pk'))),
        has_feedback_annotated=Exists(feedback_qs),
        has_rating_annotated=Exists(RetailerRating.objects.filter(order=OuterRef('pk'))),
        feedback_overall_rating_annotated=Subquery(feedback_qs.values('overall_rating')[:1], output_field=IntegerField()),
        feedback_comment_annotated=Subquery(feedback_qs.values('comment')[:1], output_field=CharField()),
        feedback_created_at_annotated=Subquery(feedback_qs.values('created_at')[:1], output_field=DateTimeField()),
    ).annotate(
        net_amount_annotated=F('total_amount') - F('refund_amount_annotated')
    )


def _adapt_orders(rows):
    return [OrderProjectionAdapter(o) for o in rows]



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
        
        base_qs = _annotated_order_queryset()

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
            serializer = OrderListSerializer(_adapt_orders(page), many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderListSerializer(_adapt_orders(orders), many=True)
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
        base_qs = _annotated_order_queryset()

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
            # Handle aliases for frontend compatibility
            if status_filter == 'shipped':
                status_filter = 'out_for_delivery'
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
            serializer = OrderListSerializer(_adapt_orders(page), many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderListSerializer(_adapt_orders(orders), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting order history: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
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
        qs = _annotated_order_queryset()

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
        
        serializer = OrderDetailSerializer(OrderProjectionAdapter(order), context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting order detail: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
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
        order.cancelled_by = user.user_type
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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
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
        
        # Apply date filters
        time_range = request.query_params.get('time_range')
        if time_range == 'today':
            orders = orders.filter(created_at__date=today)
        elif time_range == 'this_week':
            start_of_week = today - timedelta(days=today.weekday())
            orders = orders.filter(created_at__date__gte=start_of_week)
        elif time_range == 'this_month':
            orders = orders.filter(created_at__year=today.year, created_at__month=today.month)
        elif time_range == 'custom':
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            if start_date:
                try:
                    start_date_obj = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
                    orders = orders.filter(created_at__date__gte=start_date_obj)
                except ValueError:
                    pass
            if end_date:
                try:
                    end_date_obj = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
                    orders = orders.filter(created_at__date__lte=end_date_obj)
                except ValueError:
                    pass
        
        # Calculate statistics with optimized aggregation
        stats = orders.aggregate(
            total_orders=Count('id'),
            pending_orders=Count('id', filter=Q(status='pending')),
            confirmed_orders=Count('id', filter=Q(status='confirmed')),
            delivered_orders=Count('id', filter=Q(status='delivered')),
            cancelled_orders=Count('id', filter=Q(status='cancelled')),
            total_revenue=Sum('total_amount', filter=Q(status='delivered')),
            avg_order_value=Avg('total_amount', filter=Q(status='delivered')),
            
            # Accurate Payment Breakdown (respecting current filters)
            cash_sales=Sum('cash_amount', filter=Q(status='delivered')),
            digital_sales=Sum(F('upi_amount') + F('card_amount'), filter=Q(status='delivered')),
            credit_sales=Sum('credit_amount', filter=Q(status='delivered')),
            
            # Channel Performance (respecting current filters)
            pos_sales=Sum('total_amount', filter=Q(status='delivered') & Q(source='pos')),
            online_sales=Sum('total_amount', filter=Q(status='delivered') & (Q(source='app') | Q(source__isnull=True)))
        )
        
        # Aggregate Returns for correctly calculating NET revenue
        from returns.models import SalesReturn
        returns_qs = SalesReturn.objects.filter(retailer=retailer)
        if time_range == 'today':
            returns_qs = returns_qs.filter(created_at__date=today)
        elif time_range == 'this_week':
            start_of_week = today - timedelta(days=today.weekday())
            returns_qs = returns_qs.filter(created_at__date__gte=start_of_week)
        elif time_range == 'this_month':
            returns_qs = returns_qs.filter(created_at__year=today.year, created_at__month=today.month)
        elif time_range == 'custom':
            if 'start_date_obj' in locals():
                returns_qs = returns_qs.filter(created_at__date__gte=start_date_obj)
            if 'end_date_obj' in locals():
                returns_qs = returns_qs.filter(created_at__date__lte=end_date_obj)

        returns_stats = returns_qs.aggregate(
            total_refund=Sum('refund_amount'),
            cash_refund=Sum('refund_amount', filter=Q(refund_payment_mode='cash')),
            upi_refund=Sum('refund_amount', filter=Q(refund_payment_mode='upi')),
            pos_refund=Sum('refund_amount', filter=Q(order__source='pos') | Q(order__isnull=True)),
            online_refund=Sum('refund_amount', filter=Q(order__source='app'))
        )

        total_refund = returns_stats['total_refund'] or 0
        cash_refund = returns_stats['cash_refund'] or 0
        upi_refund = returns_stats['upi_refund'] or 0
        pos_refund = returns_stats['pos_refund'] or 0
        online_refund = returns_stats['online_refund'] or 0
        
        today_stats = orders.filter(created_at__date=today).aggregate(
            today_orders=Count('id'),
            today_revenue=Sum('total_amount', filter=Q(status='delivered'))
        )
        
        # Top customers (only for identified customers)
        top_customers = orders.filter(status='delivered', customer__isnull=False).values(
            'customer__first_name', 'customer__id'
        ).annotate(
            order_count=Count('id'),
            total_spent=Sum('total_amount')
        ).order_by('-total_spent')[:5]
        
        # Recent orders
        recent_orders = orders.select_related('customer').order_by('-created_at')[:10]
        recent_orders_data = []
        for order in recent_orders:
            recent_orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'customer_name': order.customer.first_name if order.customer else (order.guest_name or "Walk-in Customer"),
                'total_amount': order.total_amount,
                'status': order.status,
                'created_at': order.created_at
            })
        
        recent_feedbacks = OrderFeedback.objects.filter(
            order__retailer=retailer
        ).select_related('customer').order_by('-created_at')[:5]
        
        recent_reviews_data = []
        for feedback in recent_feedbacks:
            recent_reviews_data.append({
                'rating': feedback.overall_rating,
                'customer_name': feedback.customer.first_name or feedback.customer.username,
                'comment': feedback.comment,
                'created_at': feedback.created_at
            })
            
        stats_data = {
            'total_orders': stats['total_orders'] or 0,
            'pending_orders': stats['pending_orders'] or 0,
            'confirmed_orders': stats['confirmed_orders'] or 0,
            'delivered_orders': stats['delivered_orders'] or 0,
            'cancelled_orders': stats['cancelled_orders'] or 0,
            'total_revenue': float(stats['total_revenue'] or 0) - float(total_refund),
            'today_orders': today_stats['today_orders'] or 0,
            'today_revenue': float(today_stats['today_revenue'] or 0), # Today summary handled as partial elsewhere
            'average_order_value': stats['avg_order_value'] or 0,
            'top_customers': list(top_customers),
            'recent_orders': recent_orders_data,
            'total_products': total_products,
            'average_rating': float(retailer.average_rating),
            'recent_reviews': recent_reviews_data,
            'cash_sales': float(stats['cash_sales'] or 0) - float(cash_refund),
            'digital_sales': float(stats['digital_sales'] or 0) - float(upi_refund),
            'credit_sales': float(stats['credit_sales'] or 0),
            'pos_sales': float(stats['pos_sales'] or 0) - float(pos_refund),
            'online_sales': float(stats['online_sales'] or 0) - float(online_refund)
        }
        
        serializer = OrderStatsSerializer(stats_data)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_retailer_reviews(request):
    """
    Get all customer reviews/feedback for a retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access reviews'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        reviews = OrderFeedback.objects.filter(
            order__retailer=retailer
        ).select_related('customer', 'order').order_by('-created_at')
        
        # Pagination
        paginator = PageNumberPagination()
        paginator.page_size = 20
        paginated_reviews = paginator.paginate_queryset(reviews, request)
        
        data = []
        for feedback in paginated_reviews:
            data.append({
                'id': feedback.id,
                'order_number': feedback.order.order_number,
                'rating': feedback.overall_rating,
                'customer_name': feedback.customer.first_name or feedback.customer.username,
                'comment': feedback.comment,
                'created_at': feedback.created_at
            })
            
        return paginator.get_paginated_response(data)
    
    except Exception as e:
        logger.error(f"Error getting retailer reviews: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
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
        
        # Use transaction to ensure all changes are atomic
        with transaction.atomic():
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
                            # Recalculate max allowed discount for new total
                            total_before_points = max(Decimal('0'), order.subtotal + order.delivery_fee - (order.discount_amount or Decimal('0')))
                            
                            # Calculate max allowed discount for new total
                            # 1. Percentage limit on total_before_points
                            max_by_percent = ((total_before_points * config.max_reward_usage_percent) / Decimal('100')).quantize(Decimal('0.01'))
                            
                            # 2. Flat limit
                            max_by_flat = config.max_reward_usage_flat
                            
                            # 3. Current redeemed points value (the user "paid" this much in points initially)
                            # We don't want to use MORE points than initially redeemed, only LESS if the total dropped
                            current_points_value = (order.points_redeemed * config.conversion_rate).quantize(Decimal('0.01'))
                            
                            # New max redeemable amount
                            redeemable_amount = min(total_before_points, max_by_percent, max_by_flat, current_points_value)
                            
                            if redeemable_amount < current_points_value:
                                # Discount needs to be reduced
                                diff_value = current_points_value - redeemable_amount
                                points_to_refund = (diff_value / config.conversion_rate).quantize(Decimal('0.01'))
                                
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
                                
                    except (RetailerRewardConfig.DoesNotExist, CustomerLoyalty.DoesNotExist):
                        pass
                
                # Fetch fresh detail to return
                detail_serializer = OrderDetailSerializer(order)
                return Response(detail_serializer.data)
            
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        logger.error(f"Error modifying order: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
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
        return Response({'error': format_exception(e)}, status=500)


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
            # Create persistent notification for Customer
            if hasattr(recipient, 'customer_profile'): # Check if recipient is a customer
                from customers.models import CustomerNotification
                CustomerNotification.objects.create(
                    customer=recipient,
                    notification_type='order_update',
                    title=f"New Message: Order #{order.order_number}",
                    message=f"New message from {user.first_name or user.username}: {message_text[:50]}{'...' if len(message_text) > 50 else ''}"
                )

            send_push_notification(
                user=recipient,
                title=f"Message from {user.first_name or user.username}",
                message=message_text,
                data={
                    'type': 'new_message',
                    'order_id': str(order.id)
                }
            )
            
        serializer = OrderChatMessageSerializer(message, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return Response({'error': format_exception(e)}, status=500)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_retailer_rating(request, order_id):
    """
    Create rating for a customer - only for retailers
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can rate customers'}, 
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
        
        serializer = RetailerRatingSerializer(
            data=request.data,
            context={'order': order, 'retailer': retailer}
        )
        
        if serializer.is_valid():
            rating = serializer.save()
            logger.info(f"Rating created for customer {order.customer.username} by retailer {retailer.shop_name}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error creating retailer rating: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


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

        # Also mark related persistent notifications as read for Customer
        if user.user_type == 'customer':
            from customers.models import CustomerNotification
            # Try to match notifications related to this order. 
            # Title format: "New Message: Order #{order.order_number}"
            # or "Order #{self.order_number} Update"
            
            # Use icontains for broader matching
            CustomerNotification.objects.filter(
                customer=user, 
                title__icontains=order.order_number,
                is_read=False
            ).update(is_read=True)
        
        return Response({'status': 'ok'})
        
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error marking read: {e}")
        return Response({'error': format_exception(e)}, status=500)


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_estimated_time(request, order_id):
    """
    Update estimated ready time - only for retailers
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can update estimated time'}, 
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
            
        if order.status not in ['confirmed', 'processing']:
            return Response(
                {'error': 'Can only update time for confirmed or processing orders'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        prep_time = request.data.get('preparation_time_minutes')
        if prep_time is None:
            return Response(
                {'error': 'preparation_time_minutes is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            prep_time = int(prep_time)
            if prep_time < 0:
                raise ValueError()
        except ValueError:
            return Response(
                {'error': 'preparation_time_minutes must be a positive integer'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Update order
        from datetime import timedelta
        from django.utils import timezone
        
        order.preparation_time_minutes = prep_time
        order.estimated_ready_time = timezone.now() + timedelta(minutes=prep_time)
        order.save()
        
        # Send silent push to customer to refresh order
        from common.notifications import send_silent_update, send_push_notification
        
        send_silent_update(
            user=order.customer,
            event_type='order_refresh',
            data={'order_id': str(order.id)}
        )
        
        send_push_notification(
            user=order.customer,
            title=f"Order Update: #{order.order_number}",
            message=f"The estimated ready time for your order has been updated.",
            data={
                'type': 'order_status_update',
                'order_id': str(order.id),
                'status': order.status
            }
        )
        
        serializer = OrderDetailSerializer(order, context={'request': request})
        logger.info(f"Estimated time updated for order: {order.order_number}")
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error updating estimated time: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def submit_payment(request, order_id):
    """
    Submit/Update payment reference ID for UPI orders - only for customers
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can submit payment details'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        
        if order.payment_mode != 'upi':
            return Response(
                {'error': 'This order does not use UPI payment'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if order.is_payment_locked:
            return Response(
                {'error': 'Payment is verified and locked. Cannot edit transaction ID.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if order.payment_edit_count >= 3:
            return Response(
                {'error': 'Maximum edit attempts (3) reached.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment_reference_id = request.data.get('payment_reference_id')
        if not payment_reference_id:
            return Response(
                {'error': 'Payment reference ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # 12-digit numeric validation
        if not re.match(r'^[0-9]{12}$', str(payment_reference_id)):
            return Response(
                {'error': 'Invalid Transaction ID. Please enter a valid 12-digit numeric UPI reference number.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if it's an update or first time
        is_update = order.payment_reference_id is not None
        
        order.payment_reference_id = payment_reference_id
        order.payment_status = 'pending_verification'
        order.payment_edit_count += 1
        order.save()
        
        # Notify Retailer (wrapped in try-except to prevent 500 on notification failure)
        try:
            if order.retailer and order.retailer.user:
                title = "Payment Updated" if is_update else "Payment Submitted"
                message = f"Customer has {'updated' if is_update else 'submitted'} payment reference for Order #{order.order_number}."
                
                send_push_notification(
                    user=order.retailer.user,
                    title=title,
                    message=message,
                    data={
                        'type': 'payment_submitted',
                        'order_id': str(order.id),
                        'is_update': is_update
                    }
                )
                
                # Silent update for live reload
                send_silent_update(
                    user=order.retailer.user,
                    event_type='order_refresh',
                    data={'order_id': str(order.id)}
                )
        except Exception as notify_error:
            logger.error(f"Notification error in submit_payment: {str(notify_error)}")
        
        logger.info(f"Payment reference {'updated' if is_update else 'submitted'} for order: {order.order_number}")
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error submitting payment: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def verify_payment(request, order_id):
    """
    Verify/Reject payment - only for retailers
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can verify payments'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        retailer = RetailerProfile.objects.get(user=request.user)
        order = get_object_or_404(Order, id=order_id, retailer=retailer)
        
        action = request.data.get('action') # 'verify' or 'fail'
        if action not in ['verify', 'fail']:
            return Response(
                {'error': 'Invalid action. Use "verify" or "fail".'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if action == 'verify':
            order.payment_status = 'verified'
            order.is_payment_locked = True
            msg = f"Your UPI payment for Order #{order.order_number} has been verified."
        else:
            order.payment_status = 'failed'
            msg = f"Payment verification failed for Order #{order.order_number}. Please update the transaction ID."
        
        order.save()
        
        # Notify Customer (wrapped in try-except)
        try:
            if order.customer:
                send_push_notification(
                    user=order.customer,
                    title="Payment Update",
                    message=msg,
                    data={
                        'type': 'payment_status_update',
                        'order_id': str(order.id),
                        'payment_status': order.payment_status
                    }
                )
                
                # Send silent update
                send_silent_update(
                    user=order.customer,
                    event_type='order_refresh',
                    data={'order_id': str(order.id)}
                )
        except Exception as notify_error:
            logger.error(f"Notification error in verify_payment: {str(notify_error)}")
        
        logger.info(f"Payment {action}ed for order: {order.order_number}")
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Retailer profile not found'}, status=404)
    except Exception as e:
        logger.error(f"Error verifying payment: {str(e)}")
        return Response(
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
