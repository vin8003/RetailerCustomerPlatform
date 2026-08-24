from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.utils import timezone
from datetime import timedelta
import logging
import re
from common.error_utils import format_exception
from .models import Order, OrderChatMessage
from .serializers import OrderChatMessageSerializer, OrderDetailSerializer, RetailerRatingSerializer
from retailers.models import RetailerProfile
from common.notifications import send_push_notification, send_silent_update

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_order_chat(request, order_id):
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
        message = OrderChatMessage.objects.create(order=order, sender=user, message=message_text)
        if recipient:
            if hasattr(recipient, 'customer_profile'):
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
                data={'type': 'new_message', 'order_id': str(order.id)}
            )
        serializer = OrderChatMessageSerializer(message, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return Response({'error': format_exception(e)}, status=500)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_retailer_rating(request, order_id):
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can rate customers'}, status=status.HTTP_403_FORBIDDEN)
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
            order = get_object_or_404(Order, id=order_id, retailer=retailer)
        except RetailerProfile.DoesNotExist:
            return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = RetailerRatingSerializer(data=request.data, context={'order': order, 'retailer': retailer})
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Rating created for customer {order.customer.username} by retailer {retailer.shop_name}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error creating retailer rating: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def mark_chat_read(request, order_id):
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
        order.chat_messages.exclude(sender=user).filter(is_read=False).update(is_read=True)
        if user.user_type == 'customer':
            from customers.models import CustomerNotification
            CustomerNotification.objects.filter(customer=user, title__icontains=order.order_number, is_read=False).update(is_read=True)
        return Response({'status': 'ok'})
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error marking read: {e}")
        return Response({'error': format_exception(e)}, status=500)


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_estimated_time(request, order_id):
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can update estimated time'}, status=status.HTTP_403_FORBIDDEN)
        try:
            retailer = RetailerProfile.objects.get(user=request.user)
            order = get_object_or_404(Order, id=order_id, retailer=retailer)
        except RetailerProfile.DoesNotExist:
            return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
        if order.status not in ['confirmed', 'processing']:
            return Response({'error': 'Can only update time for confirmed or processing orders'}, status=status.HTTP_400_BAD_REQUEST)
        prep_time = request.data.get('preparation_time_minutes')
        if prep_time is None:
            return Response({'error': 'preparation_time_minutes is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            prep_time = int(prep_time)
            if prep_time < 0:
                raise ValueError()
        except ValueError:
            return Response({'error': 'preparation_time_minutes must be a positive integer'}, status=status.HTTP_400_BAD_REQUEST)
        order.preparation_time_minutes = prep_time
        order.estimated_ready_time = timezone.now() + timedelta(minutes=prep_time)
        order.save()
        send_silent_update(user=order.customer, event_type='order_refresh', data={'order_id': str(order.id)})
        send_push_notification(
            user=order.customer,
            title=f"Order Update: #{order.order_number}",
            message="The estimated ready time for your order has been updated.",
            data={'type': 'order_status_update', 'order_id': str(order.id), 'status': order.status}
        )
        serializer = OrderDetailSerializer(order, context={'request': request})
        logger.info(f"Estimated time updated for order: {order.order_number}")
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error updating estimated time: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def submit_payment(request, order_id):
    try:
        if request.user.user_type != 'customer':
            return Response({'error': 'Only customers can submit payment details'}, status=status.HTTP_403_FORBIDDEN)
        order = get_object_or_404(Order, id=order_id, customer=request.user)
        if order.payment_mode != 'upi':
            return Response({'error': 'This order does not use UPI payment'}, status=status.HTTP_400_BAD_REQUEST)
        if order.is_payment_locked:
            return Response({'error': 'Payment is verified and locked. Cannot edit transaction ID.'}, status=status.HTTP_400_BAD_REQUEST)
        if order.payment_edit_count >= 3:
            return Response({'error': 'Maximum edit attempts (3) reached.'}, status=status.HTTP_400_BAD_REQUEST)
        payment_reference_id = request.data.get('payment_reference_id')
        if not payment_reference_id:
            return Response({'error': 'Payment reference ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^[0-9]{12}$', str(payment_reference_id)):
            return Response({'error': 'Invalid Transaction ID. Please enter a valid 12-digit numeric UPI reference number.'}, status=status.HTTP_400_BAD_REQUEST)
        is_update = order.payment_reference_id is not None
        order.payment_reference_id = payment_reference_id
        order.payment_status = 'pending_verification'
        order.payment_edit_count += 1
        order.save()
        try:
            if order.retailer and order.retailer.user:
                title = "Payment Updated" if is_update else "Payment Submitted"
                message = f"Customer has {'updated' if is_update else 'submitted'} payment reference for Order #{order.order_number}."
                send_push_notification(
                    user=order.retailer.user,
                    title=title,
                    message=message,
                    data={'type': 'payment_submitted', 'order_id': str(order.id), 'is_update': is_update}
                )
                send_silent_update(user=order.retailer.user, event_type='order_refresh', data={'order_id': str(order.id)})
        except Exception as notify_error:
            logger.error(f"Notification error in submit_payment: {str(notify_error)}")
        logger.info(f"Payment reference {'updated' if is_update else 'submitted'} for order: {order.order_number}")
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error submitting payment: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def verify_payment(request, order_id):
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can verify payments'}, status=status.HTTP_403_FORBIDDEN)
        retailer = RetailerProfile.objects.get(user=request.user)
        order = get_object_or_404(Order, id=order_id, retailer=retailer)
        action = request.data.get('action')
        if action not in ['verify', 'fail']:
            return Response({'error': 'Invalid action. Use "verify" or "fail".'}, status=status.HTTP_400_BAD_REQUEST)
        if action == 'verify':
            order.payment_status = 'verified'
            order.is_payment_locked = True
            msg = f"Your UPI payment for Order #{order.order_number} has been verified."
        else:
            order.payment_status = 'failed'
            msg = f"Payment verification failed for Order #{order.order_number}. Please update the transaction ID."
        order.save()
        try:
            if order.customer:
                send_push_notification(
                    user=order.customer,
                    title="Payment Update",
                    message=msg,
                    data={'type': 'payment_status_update', 'order_id': str(order.id), 'payment_status': order.payment_status}
                )
                send_silent_update(user=order.customer, event_type='order_refresh', data={'order_id': str(order.id)})
        except Exception as notify_error:
            logger.error(f"Notification error in verify_payment: {str(notify_error)}")
        logger.info(f"Payment {action}ed for order: {order.order_number}")
        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Retailer profile not found'}, status=404)
    except Exception as e:
        logger.error(f"Error verifying payment: {str(e)}")
        return Response({'error': format_exception(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
