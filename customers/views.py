from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Count, Sum, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
import logging

from .models import CustomerProfile, CustomerAddress, CustomerWishlist, CustomerNotification, CustomerLoyalty, CustomerReferral
from .serializers import (
    CustomerProfileSerializer, CustomerAddressSerializer, CustomerAddressUpdateSerializer,
    CustomerWishlistSerializer, CustomerNotificationSerializer, CustomerDashboardSerializer,
)
from retailers.models import RetailerProfile, RetailerRewardConfig
from retailers.serializers import RetailerRewardConfigSerializer
from orders.models import Order
from products.models import Product
from retailers.models import RetailerProfile

logger = logging.getLogger(__name__)


class CustomerPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_profile(request):
    """
    Get customer profile - only for customer users
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access this endpoint'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get or create customer profile
        profile, created = CustomerProfile.objects.get_or_create(user=request.user)
        
        # Ensure referral code exists (for existing profiles created before the field was added)
        if not profile.referral_code:
            profile.save()
            
        serializer = CustomerProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting customer profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_customer_profile(request):
    """
    Update customer profile - only for customer users
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can update profile'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get or create customer profile
        profile, created = CustomerProfile.objects.get_or_create(user=request.user)
        
        serializer = CustomerProfileSerializer(
            profile, 
            data=request.data, 
            partial=request.method == 'PATCH'
        )
        
        if serializer.is_valid():
            profile = serializer.save()
            logger.info(f"Customer profile updated: {request.user.username}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error updating customer profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_addresses(request):
    """
    Get all addresses for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access addresses'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        addresses = CustomerAddress.objects.filter(
            customer=request.user, 
            is_active=True
        ).order_by('-is_default', '-created_at')
        
        serializer = CustomerAddressSerializer(addresses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting customer addresses: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_customer_address(request):
    """
    Create a new address for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can create addresses'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = CustomerAddressSerializer(
            data=request.data, 
            context={'customer': request.user}
        )
        
        if serializer.is_valid():
            address = serializer.save()
            logger.info(f"Address created for customer: {request.user.username}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error creating customer address: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_address(request, address_id):
    """
    Get a specific address for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access addresses'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        address = get_object_or_404(
            CustomerAddress, 
            id=address_id, 
            customer=request.user,
            is_active=True
        )
        
        serializer = CustomerAddressSerializer(address)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting customer address: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_customer_address(request, address_id):
    """
    Update a specific address for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can update addresses'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        address = get_object_or_404(
            CustomerAddress, 
            id=address_id, 
            customer=request.user,
            is_active=True
        )
        
        serializer = CustomerAddressUpdateSerializer(
            address, 
            data=request.data, 
            partial=request.method == 'PATCH'
        )
        
        if serializer.is_valid():
            address = serializer.save()
            response_serializer = CustomerAddressSerializer(address)
            logger.info(f"Address updated for customer: {request.user.username}")
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error updating customer address: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_customer_address(request, address_id):
    """
    Delete a specific address for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can delete addresses'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        address = get_object_or_404(
            CustomerAddress, 
            id=address_id, 
            customer=request.user,
            is_active=True
        )
        
        # Soft delete
        address.is_active = False
        address.save()
        
        logger.info(f"Address deleted for customer: {request.user.username}")
        return Response(
            {'message': 'Address deleted successfully'}, 
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        logger.error(f"Error deleting customer address: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_wishlist(request):
    """
    Get wishlist for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access wishlist'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        wishlist = CustomerWishlist.objects.filter(
            customer=request.user
        ).select_related('product', 'product__retailer').order_by('-created_at')
        
        paginator = CustomerPagination()
        page = paginator.paginate_queryset(wishlist, request)
        
        if page is not None:
            serializer = CustomerWishlistSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = CustomerWishlistSerializer(wishlist, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting customer wishlist: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_to_wishlist(request):
    """
    Add product to wishlist
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can add to wishlist'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = CustomerWishlistSerializer(
            data=request.data, 
            context={'customer': request.user}
        )
        
        if serializer.is_valid():
            try:
                wishlist_item = serializer.save()
                logger.info(f"Product added to wishlist: {request.user.username}")
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except Exception as e:
                if 'UNIQUE constraint failed' in str(e) or 'duplicate key' in str(e):
                    return Response(
                        {'error': 'Product already in wishlist'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                raise
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error adding to wishlist: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def remove_from_wishlist(request, product_id):
    """
    Remove product from wishlist
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can remove from wishlist'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        wishlist_item = get_object_or_404(
            CustomerWishlist, 
            customer=request.user,
            product_id=product_id
        )
        
        wishlist_item.delete()
        
        logger.info(f"Product removed from wishlist: {request.user.username}")
        return Response(
            {'message': 'Product removed from wishlist'}, 
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        logger.error(f"Error removing from wishlist: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_notifications(request):
    """
    Get notifications for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access notifications'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        notifications = CustomerNotification.objects.filter(
            customer=request.user
        ).order_by('-created_at')
        
        # Filter by read status if specified
        is_read = request.query_params.get('is_read')
        if is_read is not None:
            notifications = notifications.filter(is_read=is_read.lower() == 'true')
        
        paginator = CustomerPagination()
        page = paginator.paginate_queryset(notifications, request)
        
        if page is not None:
            serializer = CustomerNotificationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = CustomerNotificationSerializer(notifications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting customer notifications: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def mark_notification_read(request, notification_id):
    """
    Mark notification as read
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can mark notifications as read'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        notification = get_object_or_404(
            CustomerNotification, 
            id=notification_id, 
            customer=request.user
        )
        
        notification.is_read = True
        notification.save()
        
        serializer = CustomerNotificationSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_dashboard(request):
    """
    Get dashboard data for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access dashboard'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get orders statistics
        orders = Order.objects.filter(customer=request.user)
        total_orders = orders.count()
        pending_orders = orders.filter(status__in=['pending', 'confirmed', 'processing']).count()
        delivered_orders = orders.filter(status='delivered').count()
        cancelled_orders = orders.filter(status='cancelled').count()
        
        # Calculate total spent
        total_spent = orders.filter(status='delivered').aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        
        # Get other stats
        wishlist_count = CustomerWishlist.objects.filter(customer=request.user).count()
        addresses_count = CustomerAddress.objects.filter(customer=request.user, is_active=True).count()
        unread_notifications = CustomerNotification.objects.filter(
            customer=request.user, 
            is_read=False
        ).count()
        
        # Get recent orders
        recent_orders = orders.order_by('-created_at')[:5]
        recent_orders_data = []
        for order in recent_orders:
            recent_orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'status': order.status,
                'total_amount': order.total_amount,
                'created_at': order.created_at,
                'retailer_name': order.retailer.shop_name if order.retailer else None
            })
        
        # Get favorite retailers (based on order frequency)
        favorite_retailers = Order.objects.filter(
            customer=request.user
        ).values('retailer__id', 'retailer__shop_name').annotate(
            order_count=Count('id')
        ).order_by('-order_count')[:5]
        
        dashboard_data = {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'delivered_orders': delivered_orders,
            'cancelled_orders': cancelled_orders,
            'total_spent': total_spent,
            'wishlist_count': wishlist_count,
            'addresses_count': addresses_count,
            'unread_notifications': unread_notifications,
            'recent_orders': recent_orders_data,
            'favorite_retailers': list(favorite_retailers)
        }
        
        serializer = CustomerDashboardSerializer(dashboard_data)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting customer dashboard: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_reward_configuration(request):
    """
    Get reward configuration for a specific retailer
    """
    try:
        retailer_id = request.query_params.get('retailer_id')
        if not retailer_id:
            return Response(
                {'error': 'Retailer ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        retailer = get_object_or_404(RetailerProfile, id=retailer_id)
        
        # Get or create config for this retailer
        config, created = RetailerRewardConfig.objects.get_or_create(retailer=retailer)
            
        serializer = RetailerRewardConfigSerializer(config)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting reward configuration: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_loyalty(request):
    """
    Get loyalty points for a specific retailer
    """
    try:
        retailer_id = request.query_params.get('retailer_id')
        if not retailer_id:
            return Response(
                {'error': 'Retailer ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        retailer = get_object_or_404(RetailerProfile, id=retailer_id)
        
        # Get or create loyalty entry
        loyalty, created = CustomerLoyalty.objects.get_or_create(
            customer=request.user,
            retailer=retailer
        )
            
        return Response({
            'points': loyalty.points,
            'retailer_id': retailer.id,
            'retailer_name': retailer.shop_name
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting customer loyalty: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_all_customer_loyalty(request):
    """
    Get all loyalty points for the authenticated customer across all retailers
    """
    try:
        loyalty_records = CustomerLoyalty.objects.filter(
            customer=request.user
        ).select_related('retailer')
        
        data = []
        for record in loyalty_records:
            data.append({
                'retailer_id': record.retailer.id,
                'retailer_name': record.retailer.shop_name,
                'points': record.points,
                'updated_at': record.updated_at
            })
            
        return Response(data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting all customer loyalty: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_retailer_customers_loyalty(request):
    """
    Get all customers with loyalty points for the authenticated retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        
        loyalty_records = CustomerLoyalty.objects.filter(
            retailer=retailer
        ).select_related('customer')
        
        data = []
        for record in loyalty_records:
            data.append({
                'customer_id': record.customer.id,
                'customer_name': record.customer.get_full_name() or record.customer.username,
                'points': record.points,
                'updated_at': record.updated_at
            })
            
        return Response(data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting retailer customers loyalty: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def apply_referral_code(request):
    """
    Link a customer to a referrer for a specific retailer using a referral code
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can apply referral codes'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        referral_code = request.data.get('referral_code')
        retailer_id = request.data.get('retailer_id')
        
        if not referral_code or not retailer_id:
            return Response(
                {'error': 'Referral code and Retailer ID are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        retailer = get_object_or_404(RetailerProfile, id=retailer_id)
        
        # Find the referrer
        referrer_profile = get_object_or_404(CustomerProfile, referral_code=referral_code)
        referrer = referrer_profile.user
        
        if referrer == request.user:
            return Response(
                {'error': 'You cannot refer yourself'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # 1. Global Check: Has this user already been referred anywhere?
        if CustomerReferral.objects.filter(referee=request.user).exists():
            return Response(
                {'error': 'You have already applied a referral code.'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Existing Order Check: Has this user already placed any orders?
        if Order.objects.filter(customer=request.user).exists():
            return Response(
                {'error': 'Referral codes can only be applied by new users before their first order.'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Create the referral
        CustomerReferral.objects.create(
            referrer=referrer,
            retailer=retailer,
            referee=request.user
        )
        
        logger.info(f"Referral applied: {referrer.username} referred {request.user.username} to {retailer.shop_name}")
        return Response(
            {'message': 'Referral code applied successfully. Points will be awarded after your first successful purchase at this shop.'}, 
            status=status.HTTP_201_CREATED
        )
        
    except Exception as e:
        logger.error(f"Error applying referral code: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_referral_stats(request):
    """
    Get referral statistics for the authenticated customer
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can access referral stats'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        profile, created = CustomerProfile.objects.get_or_create(user=request.user)
        
        # Referrals made by this user
        referrals_made = CustomerReferral.objects.filter(referrer=request.user).select_related('retailer', 'referee')
        
        data = {
            'referral_code': profile.referral_code,
            'total_referrals': referrals_made.count(),
            'successful_referrals': referrals_made.filter(is_rewarded=True).count(),
            'referrals_detail': []
        }
        
        for ref in referrals_made:
            data['referrals_detail'].append({
                'referee_name': ref.referee.get_full_name() or ref.referee.username,
                'retailer_name': ref.retailer.shop_name,
                'is_rewarded': ref.is_rewarded,
                'created_at': ref.created_at
            })
            
        return Response(data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting referral stats: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

