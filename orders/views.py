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
    """Place a new order from cart"""
    try:
        if request.user.user_type != 'customer':
            return Response({'error': 'Only customers can place orders'}, status=status.HTTP_403_FORBIDDEN)
        if not request.user.is_phone_verified:
            return Response({'error': 'Please verify your phone number to place orders.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = OrderCreateSerializer(data=request.data, context={'customer': request.user})
        if serializer.is_valid():
            from retailers.models import RetailerBlacklist, RetailerProfile
            retailer_id = request.data.get('retailer_id')
            if retailer_id:
                try:
                    retailer = RetailerProfile.objects.get(id=retailer_id)
                    if RetailerBlacklist.objects.filter(retailer=retailer, customer=request.user).exists():
                        return Response({'error': 'You are blacklisted by this retailer and cannot place orders.'}, status=status.HTTP_403_FORBIDDEN)
                except RetailerProfile.DoesNotExist:
                     pass
            order = serializer.save()
            if order.retailer and order.retailer.user:
                send_push_notification(
                    user=order.retailer.user,
                    title="New Order Received!",
                    message=f"Order #{order.order_number} has been placed by {request.user.get_full_name() or request.user.username}.",
                    data={'type': 'new_order', 'order_id': str(order.id)}
                )
                from common.notifications import send_silent_update
                send_silent_update(user=order.retailer.user, event_type='order_refresh', data={'order_id': str(order.id)})
            response_serializer = OrderDetailSerializer(order, context={'request': request})
            logger.info(f"Order placed: {order.order_number} by {request.user.username}")
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_current_orders(request):
    """Get current orders for authenticated user"""
    try:
        user = request.user
        has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
        has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(
            items_count_annotated=Count('items'),
            has_feedback_annotated=has_feedback_subquery,
            has_rating_annotated=has_rating_subquery
        )
        if user.user_type == 'customer':
            orders = base_qs.filter(customer=user, status__in=['pending', 'confirmed', 'processing', 'packed', 'out_for_delivery']).order_by('-created_at')
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                orders = base_qs.filter(retailer=retailer, status__in=['pending', 'confirmed', 'processing', 'packed', 'out_for_delivery']).order_by('-created_at')
            except RetailerProfile.DoesNotExist:
                return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'error': 'Invalid user type'}, status=status.HTTP_403_FORBIDDEN)
        orders = apply_order_status_filter(orders, request.query_params.get('status'))
        search = request.query_params.get('search')
        if search:
            orders = orders.filter(order_number__icontains=search)
        paginator = OrderPagination()
        page = paginator.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = OrderListSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting current orders: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_history(request):
    """Get order history for authenticated user"""
    try:
        user = request.user
        has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
        has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(
            items_count_annotated=Count('items'),
            has_feedback_annotated=has_feedback_subquery,
            has_rating_annotated=has_rating_subquery
        )
        if user.user_type == 'customer':
            orders = base_qs.filter(customer=user).order_by('-created_at')
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                orders = base_qs.filter(retailer=retailer).order_by('-created_at')
            except RetailerProfile.DoesNotExist:
                return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'error': 'Invalid user type'}, status=status.HTTP_403_FORBIDDEN)
        # Apply filters (KAN-77: Returned includes sales-return rows)
        orders = apply_order_status_filter(orders, request.query_params.get('status'))
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
        search = request.query_params.get('search')
        if search:
            orders = orders.filter(order_number__icontains=search)
        paginator = OrderPagination()
        page = paginator.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = OrderListSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting order history: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_detail(request, order_id):
    """Get order detail for authenticated user"""
    try:
        user = request.user
        qs = Order.objects.select_related('retailer', 'customer', 'delivery_address').prefetch_related('items', 'items__product', 'items__batch')
        if user.user_type == 'customer':
            order = get_object_or_404(qs, id=order_id, customer=user)
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                order = get_object_or_404(qs, id=order_id, retailer=retailer)
            except RetailerProfile.DoesNotExist:
                return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'error': 'Invalid user type'}, status=status.HTTP_403_FORBIDDEN)
        last_updated = request.query_params.get('last_updated')
        if last_updated:
            current_updated = order.updated_at.isoformat().replace('+00:00', 'Z')
            if last_updated == current_updated or last_updated == order.updated_at.isoformat():
                return Response(status=status.HTTP_304_NOT_MODIFIED)
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting order detail: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_order_status(request, order_id):
    """Update order status - only for retailers"""
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can update order status'}, status=status.HTTP_403_FORBIDDEN)
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
            order = get_object_or_404(Order, id=order_id, retailer=retailer)
        except RetailerProfile.DoesNotExist:
            return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = OrderStatusUpdateSerializer(order, data=request.data, context={'order': order, 'user': request.user})
        if serializer.is_valid():
            order = serializer.save()
            response_serializer = OrderDetailSerializer(order, context={'request': request})
            logger.info(f"Order status updated: {order.order_number} to {order.status}")
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error updating order status: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cancel_order(request, order_id):
    """Cancel order - for customers and retailers"""
    try:
        user = request.user
        if user.user_type == 'customer':
            order = get_object_or_404(Order, id=order_id, customer=user)
        elif user.user_type == 'retailer':
            try:
                retailer = RetailerProfile.objects.get(user=user)
                order = get_object_or_404(Order, id=order_id, retailer=retailer)
            except RetailerProfile.DoesNotExist:
                return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'error': 'Invalid user type'}, status=status.HTTP_403_FORBIDDEN)
        if not order.can_be_cancelled:
            return Response({'error': 'Order cannot be cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        reason = request.data.get('reason', '')
        order.update_status('cancelled', user)
        order.cancellation_reason = reason
        order.cancelled_by = user.user_type
        order.save()
        logs_to_create = []
        items = order.items.select_related('product').all()
        for item in items:
            prev_qty = item.product.quantity
            item.product.increase_quantity(item.quantity)
            new_qty = prev_qty + item.quantity
            from products.models import ProductInventoryLog
            logs_to_create.append(ProductInventoryLog(product=item.product, log_type='returned', quantity_change=item.quantity, previous_quantity=prev_qty, new_quantity=new_qty, reason=f"Order Cancelled: #{order.order_number}", created_by=user))
        if logs_to_create:
            from products.models import ProductInventoryLog
            ProductInventoryLog.objects.bulk_create(logs_to_create)
        logger.info(f"Order cancelled: {order.order_number} by {user.username}")
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error cancelling order: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_order_feedback(request, order_id):
    """Create feedback for an order - only for customers"""
    try:
        if request.user.user_type != 'customer':
            return Response({'error': 'Only customers can provide feedback'}, status=status.HTTP_403_FORBIDDEN)
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        serializer = OrderFeedbackSerializer(data=request.data, context={'order': order, 'customer': request.user})
        if serializer.is_valid():
            feedback = serializer.save()
            logger.info(f"Feedback created for order: {order.order_number}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error creating order feedback: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_return_request(request, order_id):
    """Create return request for an order - only for customers"""
    try:
        if request.user.user_type != 'customer':
            return Response({'error': 'Only customers can create return requests'}, status=status.HTTP_403_FORBIDDEN)
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        serializer = OrderReturnSerializer(data=request.data, context={'order': order, 'customer': request.user})
        if serializer.is_valid():
            return_request = serializer.save()
            logger.info(f"Return request created for order: {order.order_number}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error creating return request: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_stats(request):
    """Get order statistics - only for retailers"""
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can access order stats'}, status=status.HTTP_403_FORBIDDEN)
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        orders = Order.objects.filter(retailer=retailer)
        from products.models import Product
        total_products = Product.objects.filter(retailer=retailer).count()
        today = timezone.now().date()
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
        stats = orders.aggregate(
            total_orders=Count('id'),
            pending_orders=Count('id', filter=Q(status='pending')),
            confirmed_orders=Count('id', filter=Q(status='confirmed')),
            delivered_orders=Count('id', filter=Q(status='delivered')),
            cancelled_orders=Count('id', filter=Q(status='cancelled')),
            total_revenue=Sum('total_amount', filter=Q(status='delivered')),
            avg_order_value=Avg('total_amount', filter=Q(status='delivered')),
            cash_sales=Sum('cash_amount', filter=Q(status='delivered')),
            digital_sales=Sum(F('upi_amount') + F('card_amount'), filter=Q(status='delivered')),
            credit_sales=Sum('credit_amount', filter=Q(status='delivered')),
            pos_sales=Sum('total_amount', filter=Q(status='delivered') & Q(source='pos')),
            online_sales=Sum('total_amount', filter=Q(status='delivered') & (Q(source='app') | Q(source__isnull=True)))
        )
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
        today_stats = orders.filter(created_at__date=today).aggregate(today_orders=Count('id'), today_revenue=Sum('total_amount', filter=Q(status='delivered')))
        top_customers = orders.filter(status='delivered', customer__isnull=False).values('customer__first_name', 'customer__id').annotate(order_count=Count('id'), total_spent=Sum('total_amount')).order_by('-total_spent')[:5]
        recent_orders = orders.select_related('customer').order_by('-created_at')[:10]
        recent_orders_data = []
        for order in recent_orders:
            recent_orders_data.append({'id': order.id, 'order_number': order.order_number, 'customer_name': order.customer.first_name if order.customer else (order.guest_name or "Walk-in Customer"), 'total_amount': order.total_amount, 'status': order.status, 'created_at': order.created_at})
        recent_feedbacks = OrderFeedback.objects.filter(order__retailer=retailer).select_related('customer').order_by('-created_at')[:5]
        recent_reviews_data = []
        for feedback in recent_feedbacks:
            recent_reviews_data.append({'rating': feedback.overall_rating, 'customer_name': feedback.customer.first_name or feedback.customer.username, 'comment': feedback.comment, 'created_at': feedback.created_at})
        stats_data = {
            'total_orders': stats['total_orders'] or 0, 'pending_orders': stats['pending_orders'] or 0,
            'confirmed_orders': stats['confirmed_orders'] or 0, 'delivered_orders': stats['delivered_orders'] or 0,
            'cancelled_orders': stats['cancelled_orders'] or 0,
            'total_revenue': float(stats['total_revenue'] or 0) - float(total_refund),
            'today_orders': today_stats['today_orders'] or 0, 'today_revenue': float(today_stats['today_revenue'] or 0),
            'average_order_value': stats['avg_order_value'] or 0, 'top_customers': list(top_customers),
            'recent_orders': recent_orders_data, 'total_products': total_products,
            'average_rating': float(retailer.average_rating), 'recent_reviews': recent_reviews_data,
            'cash_sales': float(stats['cash_sales'] or 0) - float(cash_refund),
            'digital_sales': float(stats['digital_sales'] or 0) - float(upi_refund),
            'credit_sales': float(stats['credit_sales'] or 0),
            'pos_sales': float(stats['pos_sales'] or 0) - float(pos_refund),
            'online_sales': float(stats['online_sales'] or 0) - float(online_refund)
        }
        serializer = OrderStatsSerializer(stats_data)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_retailer_reviews(request):
    """Get all customer reviews/feedback for a retailer"""
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can access reviews'}, status=status.HTTP_403_FORBIDDEN)
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        reviews = OrderFeedback.objects.filter(order__retailer=retailer).select_related('customer', 'order').order_by('-created_at')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        paginated_reviews = paginator.paginate_queryset(reviews, request)
        data = []
        for feedback in paginated_reviews:
            data.append({'id': feedback.id, 'order_number': feedback.order.order_number, 'rating': feedback.overall_rating, 'customer_name': feedback.customer.first_name or feedback.customer.username, 'comment': feedback.comment, 'created_at': feedback.created_at})
        return paginator.get_paginated_response(data)
    except Exception as e:
        logger.error(f"Error getting retailer reviews: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def modify_order(request, order_id):
    """Modify order - only for retailers"""
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can modify orders'}, status=status.HTTP_403_FORBIDDEN)
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
            order = get_object_or_404(Order, id=order_id, retailer=retailer)
        except RetailerProfile.DoesNotExist:
            return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        if order.status != 'pending':
            return Response({'error': 'Only pending orders can be modified'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            serializer = OrderModificationSerializer(order, data=request.data, context={'user': request.user})
            if serializer.is_valid():
                order = serializer.save()
                if order.points_redeemed > 0:
                    from retailers.models import RetailerRewardConfig
                    from customers.models import CustomerLoyalty
                    try:
                        config = RetailerRewardConfig.objects.filter(retailer=retailer).first()
                        loyalty = CustomerLoyalty.objects.get(customer=order.customer, retailer=retailer)
                        if config and config.is_active:
                            total_before_points = max(Decimal('0'), order.subtotal + order.delivery_fee - (order.discount_amount or Decimal('0')))
                            max_by_percent = ((total_before_points * config.max_reward_usage_percent) / Decimal('100')).quantize(Decimal('0.01'))
                            max_by_flat = config.max_reward_usage_flat
                            current_points_value = (order.points_redeemed * config.conversion_rate).quantize(Decimal('0.01'))
                            redeemable_amount = min(total_before_points, max_by_percent, max_by_flat, current_points_value)
                            if redeemable_amount < current_points_value:
                                diff_value = current_points_value - redeemable_amount
                                points_to_refund = (diff_value / config.conversion_rate).quantize(Decimal('0.01'))
                                order.discount_from_points = redeemable_amount
                                order.points_redeemed -= points_to_refund
                                order.total_amount = total_before_points - redeemable_amount
                                order.save()
                                loyalty.points += points_to_refund
                                loyalty.save()
                                logger.info(f"Points adjusted for order {order.order_number}: Refunded {points_to_refund} points")
                    except (RetailerRewardConfig.DoesNotExist, CustomerLoyalty.DoesNotExist):
                        pass
                detail_serializer = OrderDetailSerializer(order)
                return Response(detail_serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error modifying order: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def confirm_modification(request, order_id):
    """Confirm or reject order modification - only for customers"""
    try:
        if request.user.user_type != 'customer':
            return Response({'error': 'Only customers can confirm modifications'}, status=status.HTTP_403_FORBIDDEN)
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        if order.status != 'waiting_for_customer_approval':
            return Response({'error': 'Order is not waiting for approval'}, status=status.HTTP_400_BAD_REQUEST)
        action = request.data.get('action')
        if action not in ['accept', 'reject']:
            return Response({'error': 'Invalid action. Must be accept or reject'}, status=status.HTTP_400_BAD_REQUEST)
        if action == 'accept':
            order.update_status('confirmed', request.user)
            message = 'Order modification accepted'
        else:
            order.cancellation_reason = 'Customer rejected retailer modifications'
            order.update_status('cancelled', request.user)
            order.save()
            logs_to_create = []
            items = order.items.select_related('product').all()
            for item in items:
                prev_qty = item.product.quantity
                item.product.increase_quantity(item.quantity)
                new_qty = prev_qty + item.quantity
                from products.models import ProductInventoryLog
                logs_to_create.append(ProductInventoryLog(product=item.product, log_type='returned', quantity_change=item.quantity, previous_quantity=prev_qty, new_quantity=new_qty, reason=f"Modification Rejected (Order Cancelled): #{order.order_number}", created_by=request.user))
            if logs_to_create:
                from products.models import ProductInventoryLog
                ProductInventoryLog.objects.bulk_create(logs_to_create)
            message = 'Order modification rejected'
        logger.info(f"{message}: {order.order_number}")
        serializer = OrderDetailSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error confirming modification: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
