from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Avg
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
import logging

from .models import (
    RetailerProfile, RetailerOperatingHours, RetailerCategory,
    RetailerCategoryMapping, RetailerReview, RetailerRewardConfig
)
from .serializers import (
    RetailerProfileSerializer, RetailerProfileUpdateSerializer,
    RetailerListSerializer, RetailerReviewSerializer,
    RetailerCreateReviewSerializer, RetailerOperatingHoursUpdateSerializer,
    RetailerCategorySerializer, RetailerRewardConfigSerializer
)
from common.permissions import IsRetailerOwner, IsCustomerUser

logger = logging.getLogger(__name__)


class RetailerPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_retailer_profile(request):
    """
    Get retailer profile - only for retailer users
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            profile = RetailerProfile.objects.get(user=request.user)
            serializer = RetailerProfileSerializer(profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    except Exception as e:
        logger.error(f"Error getting retailer profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_retailer_profile(request):
    """
    Create retailer profile - only for retailer users
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can create retailer profile'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if profile already exists
        if RetailerProfile.objects.filter(user=request.user).exists():
            return Response(
                {'error': 'Retailer profile already exists'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = RetailerProfileUpdateSerializer(data=request.data)
        if serializer.is_valid():
            profile = serializer.save(user=request.user)
            
            # Create default operating hours (Monday to Sunday, 9 AM to 9 PM)
            days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            for day in days:
                RetailerOperatingHours.objects.create(
                    retailer=profile,
                    day_of_week=day,
                    is_open=True,
                    opening_time='09:00',
                    closing_time='21:00'
                )
            
            response_serializer = RetailerProfileSerializer(profile)
            logger.info(f"Retailer profile created: {profile.shop_name}")
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error creating retailer profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_retailer_profile(request):
    """
    Update retailer profile - only for retailer users
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can update retailer profile'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            profile = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = RetailerProfileUpdateSerializer(
            profile, 
            data=request.data, 
            partial=request.method == 'PATCH'
        )
        
        if serializer.is_valid():
            profile = serializer.save()
            response_serializer = RetailerProfileSerializer(profile)
            logger.info(f"Retailer profile updated: {profile.shop_name}")
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error updating retailer profile: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def list_retailers(request):
    """
    List retailers with filtering and search
    """
    try:
        queryset = RetailerProfile.objects.filter(is_active=True).prefetch_related('categories__category')
        
        # Apply filters
        city = request.query_params.get('city')
        state = request.query_params.get('state')
        pincode = request.query_params.get('pincode')
        category = request.query_params.get('category')
        offers_delivery = request.query_params.get('offers_delivery')
        offers_pickup = request.query_params.get('offers_pickup')
        min_rating = request.query_params.get('min_rating')
        
        if city:
            queryset = queryset.filter(city__icontains=city)
        
        if state:
            queryset = queryset.filter(state__icontains=state)
        
        if pincode:
            queryset = queryset.filter(pincode=pincode)
        
        if category:
            queryset = queryset.filter(categories__category__name__icontains=category)
        
        if offers_delivery:
            queryset = queryset.filter(offers_delivery=offers_delivery.lower() == 'true')
        
        if offers_pickup:
            queryset = queryset.filter(offers_pickup=offers_pickup.lower() == 'true')
        
        if min_rating:
            try:
                min_rating = float(min_rating)
                queryset = queryset.filter(average_rating__gte=min_rating)
            except ValueError:
                pass
        
        # Search functionality
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(shop_name__icontains=search) |
                Q(shop_description__icontains=search) |
                Q(business_type__icontains=search)
            )
        
        # Ordering
        ordering = request.query_params.get('ordering', '-average_rating')
        if ordering in ['shop_name', '-shop_name', 'average_rating', '-average_rating', 'created_at', '-created_at']:
            queryset = queryset.order_by(ordering)
        
        # Location-based filtering (if coordinates provided)
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        max_distance = request.query_params.get('max_distance')
        
        if lat and lng:
            try:
                lat = float(lat)
                lng = float(lng)
                request.user_location = (lat, lng)
                
                if max_distance:
                    max_distance = float(max_distance)
                    # Filter by distance (simplified - in production, use PostGIS)
                    filtered_retailers = []
                    for retailer in queryset:
                        distance = retailer.get_distance_from(lat, lng)
                        if distance and distance <= max_distance:
                            filtered_retailers.append(retailer.id)
                    queryset = queryset.filter(id__in=filtered_retailers)
            except ValueError:
                pass
        
        # Pagination
        paginator = RetailerPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = RetailerListSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = RetailerListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error listing retailers: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_retailer_detail(request, retailer_id):
    """
    Get detailed information about a specific retailer
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        serializer = RetailerProfileSerializer(retailer)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting retailer detail: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_retailer_categories(request):
    """
    Get all retailer categories
    """
    try:
        categories = RetailerCategory.objects.filter(is_active=True)
        serializer = RetailerCategorySerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting retailer categories: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_retailer_reviews(request, retailer_id):
    """
    Get reviews for a specific retailer
    """
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id)
        reviews = RetailerReview.objects.filter(retailer=retailer).select_related('customer').order_by('-created_at')
        
        # Pagination
        paginator = RetailerPagination()
        page = paginator.paginate_queryset(reviews, request)
        
        if page is not None:
            serializer = RetailerReviewSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = RetailerReviewSerializer(reviews, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error getting retailer reviews: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_retailer_review(request, retailer_id):
    """
    Create a review for a retailer - only for customers
    """
    try:
        if request.user.user_type != 'customer':
            return Response(
                {'error': 'Only customers can create reviews'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        retailer = get_object_or_404(RetailerProfile, id=retailer_id)
        
        serializer = RetailerCreateReviewSerializer(
            data=request.data,
            context={'retailer': retailer, 'customer': request.user}
        )
        
        if serializer.is_valid():
            review = serializer.save()
            response_serializer = RetailerReviewSerializer(review)
            logger.info(f"Review created for retailer {retailer.shop_name} by {request.user.username}")
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e:
        logger.error(f"Error creating retailer review: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_operating_hours(request):
    """
    Update retailer operating hours - only for retailer users
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can update operating hours'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            profile = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Expect list of operating hours
        operating_hours_data = request.data.get('operating_hours', [])
        
        if not operating_hours_data:
            return Response(
                {'error': 'Operating hours data is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        updated_hours = []
        for hour_data in operating_hours_data:
            day_of_week = hour_data.get('day_of_week')
            
            if not day_of_week:
                continue
            
            try:
                operating_hour = RetailerOperatingHours.objects.get(
                    retailer=profile,
                    day_of_week=day_of_week
                )
                
                serializer = RetailerOperatingHoursUpdateSerializer(
                    operating_hour,
                    data=hour_data,
                    partial=True
                )
                
                if serializer.is_valid():
                    updated_hour = serializer.save()
                    updated_hours.append(updated_hour)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                    
            except RetailerOperatingHours.DoesNotExist:
                # Create new operating hour
                serializer = RetailerOperatingHoursUpdateSerializer(data=hour_data)
                if serializer.is_valid():
                    updated_hour = serializer.save(retailer=profile)
                    updated_hours.append(updated_hour)
                else:
                    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Return updated profile
        profile.refresh_from_db()
        response_serializer = RetailerProfileSerializer(profile)
        logger.info(f"Operating hours updated for retailer: {profile.shop_name}")
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error updating operating hours: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def search_retailers(request):
    """
    Advanced search for retailers
    """
    try:
        query = request.query_params.get('q', '')
        
        if not query:
            return Response(
                {'error': 'Search query is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Search in multiple fields
        queryset = RetailerProfile.objects.filter(
            Q(shop_name__icontains=query) |
            Q(shop_description__icontains=query) |
            Q(business_type__icontains=query) |
            Q(city__icontains=query) |
            Q(state__icontains=query) |
            Q(categories__category__name__icontains=query),
            is_active=True
        ).prefetch_related('categories__category').distinct()
        
        # Apply additional filters
        city = request.query_params.get('city')
        if city:
            queryset = queryset.filter(city__icontains=city)
        
        # Ordering
        queryset = queryset.order_by('-average_rating', 'shop_name')
        
        # Pagination
        paginator = RetailerPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = RetailerListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = RetailerListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error searching retailers: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def manage_reward_configuration(request):
    """
    Get or update retailer reward configuration
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access this endpoint'}, 
                status=status.HTTP_403_FORBIDDEN
            )
            
        profile = get_object_or_404(RetailerProfile, user=request.user)
        
        # Get or create config
        config, created = RetailerRewardConfig.objects.get_or_create(retailer=profile)
        
        if request.method == 'GET':
            serializer = RetailerRewardConfigSerializer(config)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        elif request.method == 'PUT':
            serializer = RetailerRewardConfigSerializer(config, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error managing reward config: {str(e)}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
