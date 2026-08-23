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
                send_push_notification(user=order.retailer.user, title="New Order Received!", message=f"Order #{order.order_number} has been placed by {request.user.get_full_name() or request.user.username}.", data={'type': 'new_order', 'order_id': str(order.id)})
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
    try:
        user = request.user
        has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
        has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(items_count_annotated=Count('items'), has_feedback_annotated=has_feedback_subquery, has_rating_annotated=has_rating_subquery)
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
    try:
        user = request.user
        has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
        has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))
        base_qs = Order.objects.select_related('retailer', 'customer').annotate(items_count_annotated=Count('items'), has_feedback_annotated=has_feedback_subquery, has_rating_annotated=has_rating_subquery)
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
    try:
        if request.user.user_type != 'customer':
            return Response({'error': 'Only customers can provide feedback'}, status=status.HTTP_403_FORBIDDEN)
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        serializer = OrderFeedbackSerializer(data=request.data, context={'order': order, 'customer': request.user})
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Feedback created for order: {order.order_number}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error creating order feedback: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_return_request(request, order_id):
    try:
        if request.user.user_type != 'customer':
            return Response({'error': 'Only customers can create return requests'}, status=status.HTTP_403_FORBIDDEN)
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        serializer = OrderReturnSerializer(data=request.data, context={'order': order, 'customer': request.user})
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Return request created for order: {order.order_number}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error creating return request: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# FILE_CONTINUES_IN_NEXT_COMMIT
