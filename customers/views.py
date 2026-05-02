from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Count, Sum, Q
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Q, Count, Avg
from common.pagination import StandardResultsSetPagination
from django.utils import timezone
from datetime import timedelta
import logging

from django.contrib.auth import get_user_model
from .models import CustomerProfile, CustomerAddress, CustomerWishlist, CustomerNotification, CustomerLoyalty, CustomerReferral, LoyaltyTransaction
from .serializers import (
    CustomerProfileSerializer, CustomerAddressSerializer, CustomerAddressUpdateSerializer,
    CustomerWishlistSerializer, CustomerNotificationSerializer, CustomerDashboardSerializer,
    RetailerCustomerListSerializer, RetailerCustomerDetailSerializer,
    CustomerLedgerSerializer,
)
from retailers.models import RetailerProfile, RetailerRewardConfig, RetailerBlacklist, RetailerCustomerMapping, CustomerLedger
from retailers.serializers import RetailerRewardConfigSerializer
from orders.models import Order, RetailerRating
from products.models import Product

User = get_user_model()

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
        
        # Prefetch reward configs to avoid N+1
        from retailers.models import RetailerRewardConfig
        retailer_ids = [record.retailer.id for record in loyalty_records]
        configs = RetailerRewardConfig.objects.filter(retailer__id__in=retailer_ids)
        config_map = {config.retailer.id: config.conversion_rate for config in configs}
        logger.debug(f"DEBUG: loyalty_records counts={len(loyalty_records)}")
        logger.debug(f"DEBUG: config_map counts={len(config_map)}")
        
        # Fetch upcoming expiries
        from django.db.models import Min, Sum
        expiries = LoyaltyTransaction.objects.filter(
            customer=request.user,
            transaction_type='earn',
            is_expired=False,
            expiry_date__isnull=False
        ).values('retailer_id').annotate(
            next_expiry=Min('expiry_date'),
            amount=Sum('amount')
        )
        logger.debug(f"DEBUG: expiries counts={len(expiries)}")
        expiry_map = {e['retailer_id']: {'date': e['next_expiry'], 'amount': e['amount']} for e in expiries}
        
        data = []
        for record in loyalty_records:
            # Safer conversion rate handling
            raw_rate = config_map.get(record.retailer.id, 1.0)
            conversion_rate = float(raw_rate) if raw_rate is not None else 1.0
            
            expiry_info = expiry_map.get(record.retailer.id)
            
            # Robust point calculation
            pts_float = float(record.points) if record.points else 0.0
            val_in_curr = pts_float * conversion_rate
            
            data.append({
                'retailer_id': record.retailer.id,
                'retailer_name': record.retailer.shop_name,
                'points': pts_float,
                'conversion_rate': conversion_rate,
                'value_in_currency': val_in_curr,
                'next_expiry_date': expiry_info['date'] if expiry_info else None,
                'points_expiring_soon': float(expiry_info['amount'] or 0) if expiry_info else 0,
                'updated_at': record.updated_at
            })
            
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_loyalty_transactions(request):
    """
    Get history of loyalty point transactions
    """
    retailer_id = request.query_params.get('retailer_id')
    transactions = LoyaltyTransaction.objects.filter(customer=request.user)
    
    if retailer_id:
        transactions = transactions.filter(retailer_id=retailer_id)
        
    transactions = transactions.select_related('retailer').order_by('-created_at')[:50]
    
    data = []
    for tx in transactions:
        data.append({
            'id': tx.id,
            'retailer_id': tx.retailer.id,
            'retailer_name': tx.retailer.shop_name,
            'amount': tx.amount,
            'transaction_type': tx.transaction_type,
            'description': tx.description,
            'expiry_date': tx.expiry_date,
            'is_expired': tx.is_expired,
            'created_at': tx.created_at
        })
        
    return Response(data, status=status.HTTP_200_OK)


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
        
        # Check if referral is enabled for this retailer
        config = RetailerRewardConfig.objects.filter(retailer=retailer).first()
        if not config or not config.is_referral_enabled:
            return Response(
                {'error': 'Referral system is currently disabled for this retailer'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
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
        
        # Get active referral schemes for rule visibility
        from retailers.models import RetailerRewardConfig
        active_configs = RetailerRewardConfig.objects.filter(is_referral_enabled=True, is_active=True).select_related('retailer')
        active_schemes = []
        for config in active_configs:
            active_schemes.append({
                'retailer_id': config.retailer.id,
                'retailer_name': config.retailer.shop_name,
                'referral_reward_points': config.referral_reward_points,
                'referee_reward_points': config.referee_reward_points,
                'min_referral_order_amount': config.min_referral_order_amount
            })

        data = {
            'referral_code': profile.referral_code,
            'total_referrals': referrals_made.count(),
            'successful_referrals': referrals_made.filter(is_rewarded=True).count(),
            'referrals_detail': [],
            'active_referral_schemes': active_schemes
        }
        
        # Build map of reward configs for past referrals to show rules accurately
        # (Though current rewards are fixed at delivery time, showing current rules is helpful)
        for ref in referrals_made:
            ref_config = RetailerRewardConfig.objects.filter(retailer=ref.retailer).first()
            data['referrals_detail'].append({
                'referee_name': ref.referee.get_full_name() or ref.referee.username,
                'retailer_name': ref.retailer.shop_name,
                'is_rewarded': ref.is_rewarded,
                'created_at': ref.created_at,
                'reward_rules': {
                    'your_reward': ref_config.referral_reward_points if ref_config else 0,
                    'friend_reward': ref_config.referee_reward_points if ref_config else 0,
                    'min_order_condition': ref_config.min_referral_order_amount if ref_config else 0,
                }
            })
            
        return Response(data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting referral stats: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_retailer_customers(request):
    """
    Get all customers for the authenticated retailer with rich operational data.
    Optimized with annotations to avoid N+1 queries.
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        
        # 1. Get all customer mappings with annotations
        from django.db.models import Subquery, OuterRef, Max
        from django.db.models.functions import Coalesce
        
        mappings = RetailerCustomerMapping.objects.filter(
            retailer=retailer
        ).select_related('customer', 'customer__customer_profile').annotate(
            _total_orders=Coalesce(
                Count('customer__orders', filter=Q(customer__orders__retailer=retailer)),
                0
            ),
            _total_spent=Coalesce(
                Sum('customer__orders__total_amount', filter=Q(
                    customer__orders__retailer=retailer,
                    customer__orders__status='delivered'
                )),
                0
            ),
            _last_order_date=Max('customer__orders__created_at', filter=Q(
                customer__orders__retailer=retailer
            ))
        ).order_by('-created_at')
        
        # 2. Apply Search Filter if present
        search = request.query_params.get('search')
        if search:
            mappings = mappings.filter(
                Q(nickname__icontains=search) |
                Q(customer__first_name__icontains=search) |
                Q(customer__last_name__icontains=search) |
                Q(customer__phone_number__icontains=search)
            )

        # 3. Apply Pagination
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(mappings, request)
        
        target_mappings = page if page is not None else mappings
        
        # 4. Pre-fetch loyalty points and blacklist status in bulk (2 queries instead of 2*N)
        customer_ids = [m.customer_id for m in target_mappings]
        
        loyalty_map = dict(
            CustomerLoyalty.objects.filter(
                retailer=retailer, customer_id__in=customer_ids
            ).values_list('customer_id', 'points')
        )
        
        blacklisted_ids = set(
            RetailerBlacklist.objects.filter(
                retailer=retailer, customer_id__in=customer_ids
            ).values_list('customer_id', flat=True)
        )
        
        data = []
        for mapping in target_mappings:
            user = mapping.customer
            profile = getattr(user, 'customer_profile', None)
            customer_name = mapping.nickname or user.get_full_name() or user.username
            
            data.append({
                'customer_id': user.id,
                'customer_name': customer_name,
                'nickname': mapping.nickname,
                'phone_number': user.phone_number,
                'profile_image': profile.profile_image.url if profile and profile.profile_image else None,
                'points': loyalty_map.get(user.id, 0),
                'registration_status': user.registration_status if user.registration_status else ('registered' if user.is_phone_verified else 'shadow'),
                'is_phone_verified': user.is_phone_verified,
                'average_rating': profile.average_rating if profile else 0,
                'total_orders': mapping._total_orders,
                'total_spent': mapping._total_spent,
                'is_blacklisted': user.id in blacklisted_ids,
                'last_order_date': mapping._last_order_date,
                'joined_date': mapping.created_at,
                'current_balance': mapping.current_balance
            })
            
        serializer = RetailerCustomerListSerializer(data, many=True)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
            
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting retailer customers: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_details_for_retailer(request, customer_id):
    """
    Get detailed customer view for a retailer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        user = get_object_or_404(User, id=customer_id)
        mapping = get_object_or_404(RetailerCustomerMapping, retailer=retailer, customer=user)
        profile = getattr(user, 'customer_profile', None)
        
        # Stats
        orders = Order.objects.filter(retailer=retailer, customer=user).order_by('-created_at')
        delivered_orders = orders.filter(status='delivered')
        
        total_orders = orders.count()
        total_spent = delivered_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        last_order = orders.first()
        
        # Points
        loyalty = CustomerLoyalty.objects.filter(retailer=retailer, customer=user).first()
        points = loyalty.points if loyalty else 0
        
        # Blacklist
        is_blacklisted = RetailerBlacklist.objects.filter(retailer=retailer, customer=user).exists()
        
        # Recent Orders Data
        recent_orders_data = []
        for order in orders[:10]: # Increased to 10
            # Check if rated
            rating_obj = RetailerRating.objects.filter(order=order, retailer=retailer).first()
            rating_val = rating_obj.rating if rating_obj else None
            
            recent_orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'status': order.status,
                'total_amount': order.total_amount,
                'created_at': order.created_at,
                'items_count': order.items.count(),
                'my_rating': rating_val
            })
            
        # Reward History (Simplification: using Order logs or just returning empty for now if no dedicated log)
        # We can simulate reward history from 'points_earned' in orders
        reward_history = []
        for order in delivered_orders.filter(points_earned__gt=0).order_by('-created_at')[:5]:
             reward_history.append({
                 'date': order.delivered_at or order.updated_at,
                 'points': order.points_earned,
                 'type': 'earned',
                 'order_number': order.order_number
             })
             
        # Retailer Ratings (My ratings for this customer)
        my_ratings_qs = RetailerRating.objects.filter(retailer=retailer, customer=user).order_by('-created_at')
        my_ratings = []
        for rating in my_ratings_qs:
            my_ratings.append({
                'rating': rating.rating,
                'comment': rating.comment,
                'created_at': rating.created_at,
                'order_number': rating.order.order_number
            })
            
        data = {
            'customer_id': user.id,
            'customer_name': mapping.nickname or user.get_full_name() or user.username,
            'nickname': mapping.nickname,
            'notes': mapping.notes,
            'phone_number': user.phone_number,
            'email': user.email,
            'profile_image': profile.profile_image.url if profile and profile.profile_image else None,
            'points': points,
            'average_rating': profile.average_rating if profile else 0,
            'total_orders': total_orders,
            'total_spent': total_spent,
            'is_blacklisted': is_blacklisted,
            'last_order_date': last_order.created_at if last_order else None,
            'joined_date': mapping.created_at,
            'registration_status': user.registration_status,
            'is_phone_verified': user.is_phone_verified,
            'credit_limit': mapping.credit_limit,
            'current_balance': mapping.current_balance,
            'recent_orders': recent_orders_data,
            'reward_history': reward_history,
            'retailer_ratings': my_ratings
        }
        
        serializer = RetailerCustomerDetailSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting customer details: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def toggle_blacklist(request):
    """
    Toggle blacklist status for a customer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can manage blacklist'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        customer_id = request.data.get('customer_id')
        reason = request.data.get('reason', '')
        action = request.data.get('action') # 'blacklist' or 'unblacklist'
        
        if not customer_id or not action:
            return Response(
                {'error': 'Customer ID and action are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        customer_profile = get_object_or_404(CustomerProfile, user__id=customer_id)
        customer = customer_profile.user
        
        if action == 'blacklist':
            RetailerBlacklist.objects.get_or_create(
                retailer=retailer,
                customer=customer,
                defaults={'reason': reason}
            )
            message = 'Customer blacklisted successfully'
        elif action == 'unblacklist':
            RetailerBlacklist.objects.filter(
                retailer=retailer,
                customer=customer
            ).delete()
            message = 'Customer removed from blacklist'
        else:
             return Response(
                {'error': 'Invalid action'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        return Response({'message': message}, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error toggling blacklist: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_retailer_customer(request, customer_id):
    """
    Update retailer-specific customer mapping (nickname and notes)
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        user = get_object_or_404(User, id=customer_id)
        
        mapping = get_object_or_404(RetailerCustomerMapping, retailer=retailer, customer=user)
        
        nickname = request.data.get('nickname')
        notes = request.data.get('notes')
        
        if nickname is not None:
            mapping.nickname = nickname
        if notes is not None:
            mapping.notes = notes
            
        mapping.save()
        
        return Response({
            'message': 'Customer updated successfully',
            'nickname': mapping.nickname,
            'notes': mapping.notes
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error updating retailer customer mapping: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_customer_ledger(request, customer_id):
    """
    Get full ledger (Khata) for a customer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can access this endpoint'}, status=status.HTTP_403_FORBIDDEN)
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        user = get_object_or_404(User, id=customer_id)
        mapping = get_object_or_404(RetailerCustomerMapping, retailer=retailer, customer=user)
        
        ledger_entries = mapping.ledger_entries.all()
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(ledger_entries, request)
        
        if page is not None:
            serializer = CustomerLedgerSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        serializer = CustomerLedgerSerializer(ledger_entries, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting customer ledger: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def record_customer_payment(request):
    """
    Record a manual payment from a customer (Credit to Ledger)
    """
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can record payments'}, status=status.HTTP_403_FORBIDDEN)
            
        customer_id = request.data.get('customer_id')
        amount = request.data.get('amount')
        payment_mode = request.data.get('payment_mode', 'cash')
        notes = request.data.get('notes', 'Manual payment collection')
        
        if not customer_id or not amount:
            return Response({'error': 'Customer ID and amount are required'}, status=status.HTTP_400_BAD_REQUEST)
            
        from decimal import Decimal
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                return Response({'error': 'Amount must be positive'}, status=status.HTTP_400_BAD_REQUEST)
        except:
            return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        user = get_object_or_404(User, id=customer_id)
        mapping = get_object_or_404(RetailerCustomerMapping, retailer=retailer, customer=user)
        
        ledger_entry = mapping.record_transaction(
            transaction_type='PAYMENT',
            amount=amount,
            payment_mode=payment_mode,
            notes=notes
        )
        
        return Response({
            'message': 'Payment recorded successfully',
            'new_balance': mapping.current_balance,
            'entry': CustomerLedgerSerializer(ledger_entry).data
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error recording customer payment: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_customer_credit_limit(request, customer_id):
    """
    Update credit limit for a customer
    """
    try:
        if request.user.user_type != 'retailer':
            return Response({'error': 'Only retailers can manage credit limits'}, status=status.HTTP_403_FORBIDDEN)
            
        credit_limit = request.data.get('credit_limit')
        if credit_limit is None:
            return Response({'error': 'Credit limit is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        from decimal import Decimal
        try:
            credit_limit = Decimal(str(credit_limit))
            if credit_limit < 0:
                return Response({'error': 'Credit limit cannot be negative'}, status=status.HTTP_400_BAD_REQUEST)
        except:
            return Response({'error': 'Invalid credit limit'}, status=status.HTTP_400_BAD_REQUEST)
            
        retailer = get_object_or_404(RetailerProfile, user=request.user)
        user = get_object_or_404(User, id=customer_id)
        mapping = get_object_or_404(RetailerCustomerMapping, retailer=retailer, customer=user)
        
        mapping.credit_limit = credit_limit
        mapping.save(update_fields=['credit_limit', 'updated_at'])
        
        return Response({
            'message': 'Credit limit updated successfully',
            'credit_limit': mapping.credit_limit
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error updating credit limit: {str(e)}")
        return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

