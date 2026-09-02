from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.throttling import AnonRateThrottle
from django.db.models import Q, Avg
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
import ipaddress
import logging
import requests
from common.error_utils import format_exception

from .models import (
    Organization, RetailerProfile, RetailerOperatingHours, RetailerCategory,
    RetailerCategoryMapping, RetailerReview, RetailerRewardConfig,
    OrgRole, OrgStaffMembership, OrgStaffRoleAudit, OrgApiKey,
)
from .serializers import (
    RetailerProfileSerializer, RetailerProfileUpdateSerializer,
    RetailerListSerializer, RetailerReviewSerializer,
    RetailerCreateReviewSerializer, RetailerOperatingHoursUpdateSerializer,
    RetailerOperatingHoursSerializer,
    RetailerCategorySerializer, RetailerRewardConfigSerializer,
    OrganizationSerializer, OrganizationCreateSerializer, OrganizationUpdateSerializer,
    OrgRoleSerializer, OrgRoleCreateSerializer, OrgRoleUpdateSerializer,
    OrgStaffMembershipSerializer, OrgStaffAssignSerializer, OrgStaffUpdateSerializer,
    OrgApiKeySerializer, OrgApiKeyCreateSerializer, OrgApiKeyUpdateSerializer,
)
from .organization import (
    ensure_organization_for_profile,
    ensure_org_rbac_bootstrap,
    user_is_org_staff_admin,
    user_has_org_permission,
    user_belongs_to_organization,
    would_remove_last_owner,
    record_staff_role_audit,
)
from .api_keys import (
    create_org_api_key,
    revoke_org_api_key,
    update_org_api_key_scopes,
)
from .api_scopes import scope_catalog_payload
from .permissions_catalog import (
    ALL_PERMISSION_CODES,
    ROLE_SLUG_ADMIN,
    catalog_payload,
)
from django.contrib.auth import get_user_model
from django.db import transaction
from common.permissions import IsRetailerOwner, IsCustomerUser

User = get_user_model()
logger = logging.getLogger(__name__)


class GeoEstimateThrottle(AnonRateThrottle):
    scope = 'geo_estimate'


# Map common state abbreviations ↔ full names for retailer filters
_STATE_CODE_TO_NAME = {
    'AN': 'Andaman and Nicobar Islands',
    'AP': 'Andhra Pradesh',
    'AR': 'Arunachal Pradesh',
    'AS': 'Assam',
    'BR': 'Bihar',
    'CH': 'Chandigarh',
    'CT': 'Chhattisgarh',
    'CG': 'Chhattisgarh',
    'DN': 'Dadra and Nagar Haveli and Daman and Diu',
    'DD': 'Dadra and Nagar Haveli and Daman and Diu',
    'DL': 'Delhi',
    'GA': 'Goa',
    'GJ': 'Gujarat',
    'HR': 'Haryana',
    'HP': 'Himachal Pradesh',
    'JK': 'Jammu and Kashmir',
    'JH': 'Jharkhand',
    'KA': 'Karnataka',
    'KL': 'Kerala',
    'LA': 'Ladakh',
    'LD': 'Lakshadweep',
    'MP': 'Madhya Pradesh',
    'MH': 'Maharashtra',
    'MN': 'Manipur',
    'ML': 'Meghalaya',
    'MZ': 'Mizoram',
    'NL': 'Nagaland',
    'OR': 'Odisha',
    'OD': 'Odisha',
    'PY': 'Puducherry',
    'PB': 'Punjab',
    'RJ': 'Rajasthan',
    'SK': 'Sikkim',
    'TN': 'Tamil Nadu',
    'TS': 'Telangana',
    'TG': 'Telangana',
    'TR': 'Tripura',
    'UP': 'Uttar Pradesh',
    'UK': 'Uttarakhand',
    'UA': 'Uttarakhand',
    'WB': 'West Bengal',
}
_STATE_NAME_TO_CODES = {}
for _code, _name in _STATE_CODE_TO_NAME.items():
    _STATE_NAME_TO_CODES.setdefault(_name.lower(), []).append(_code)


def _state_filter_q(state: str) -> Q:
    """Match full state name or common abbreviation (case-insensitive)."""
    variants = {state}
    upper = state.strip().upper()
    if upper in _STATE_CODE_TO_NAME:
        variants.add(_STATE_CODE_TO_NAME[upper])
    for code in _STATE_NAME_TO_CODES.get(state.strip().lower(), []):
        variants.add(code)
    q = Q()
    for v in variants:
        q |= Q(state__iexact=v)
    return q


def _parse_bool(value, *, default: bool) -> bool:
    """Read a query-string boolean.

    Absent, blank, or unrecognised values keep `default` so a typo cannot
    silently disable a safety-on flag such as filter_by_radius.
    """
    if value is None:
        return default
    token = str(value).strip().lower()
    if token == '':
        return default
    if token in ('true', '1', 'yes'):
        return True
    if token in ('false', '0', 'no'):
        return False
    return default


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        )
    except ValueError:
        return False


class RetailerPagination(PageNumberPagination):
    """Paginator for GET /api/retailers/. max_page_size is 100 because the
    customer city map sends page_size=100. Do not swap this for
    common.pagination.RetailerPagination (that class caps at 50).
    """
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
            {'error': format_exception(e)}, 
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
            ensure_organization_for_profile(profile)

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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
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
        has_referral = request.query_params.get('has_referral')
        
        if city:
            queryset = queryset.filter(city__iexact=city)
        
        if state:
            queryset = queryset.filter(_state_filter_q(state))
        
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
        
        if has_referral:
            queryset = queryset.filter(reward_config__is_referral_enabled=has_referral.lower() == 'true')
        
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
        user_pincode = request.query_params.get('user_pincode')

        # Map/discovery clients pass filter_by_radius=false so distances are
        # computed without hiding shops outside their delivery radius.
        filter_by_radius = _parse_bool(
            request.query_params.get('filter_by_radius'), default=True
        )

        if lat and lng:
            try:
                lat = float(lat)
                lng = float(lng)
            except ValueError:
                lat = lng = None

            if lat is not None and lng is not None:
                request.user_location = (lat, lng)

                if filter_by_radius:
                    # Filter by distance and serviceable pincodes
                    filtered_retailer_ids = []
                    for retailer in queryset:
                        # 1. Check Pincode Specific Restriction
                        if user_pincode and isinstance(retailer.serviceable_pincodes, list):
                            if user_pincode in retailer.serviceable_pincodes:
                                filtered_retailer_ids.append(retailer.id)
                                continue
                            elif retailer.pincode != user_pincode and retailer.serviceable_pincodes:
                                 # If pincodes are restricted and user's pincode is not in it, skip
                                 # unless it's their own pincode (which is always serviceable?)
                                 # Actually if they specify serviceable_pincodes, it overrides?
                                 # Let's say: if serviceable_pincodes is set, it MUST be in it.
                                 pass
                        elif user_pincode and isinstance(retailer.serviceable_pincodes, str):
                            if user_pincode == retailer.serviceable_pincodes:
                                filtered_retailer_ids.append(retailer.id)
                                continue
                            elif retailer.pincode != user_pincode and retailer.serviceable_pincodes:
                                 # If pincodes are restricted and user's pincode is not in it, skip
                                 # unless it's their own pincode (which is always serviceable?)
                                 # Actually if they specify serviceable_pincodes, it overrides?
                                 # Let's say: if serviceable_pincodes is set, it MUST be in it.
                                 pass

                        # 2. Check Distance Restriction
                        distance = retailer.get_distance_from(lat, lng)
                        if distance is not None:
                             # Use retailer's specific radius or default to 5km
                             radius = retailer.delivery_radius or 5
                             if distance <= radius:
                                 filtered_retailer_ids.append(retailer.id)

                    queryset = queryset.filter(id__in=filtered_retailer_ids)
        elif user_pincode:
            # If coordinates not provided but pincode is, filter by pincode
            queryset = queryset.filter(
                Q(pincode=user_pincode) | 
                Q(serviceable_pincodes__contains=user_pincode)
            )
        
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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def list_operational_cities(request):
    """
    Distinct city/state pairs for active retailers (lightweight empty-state helper).
    """
    try:
        cities = list(
            RetailerProfile.objects.filter(is_active=True)
            .exclude(city__isnull=True)
            .exclude(city='')
            .exclude(state__isnull=True)
            .exclude(state='')
            .values('city', 'state')
            .distinct()
            .order_by('state', 'city')
        )
        return Response({'results': cities}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error listing operational cities: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _client_ip(request):
    """Prefer REMOTE_ADDR; only use first X-Forwarded-For hop when present (proxy)."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
@throttle_classes([GeoEstimateThrottle])
def geo_estimate(request):
    """
    Fallback IP→city estimate for the customer app when browser IP APIs fail.
    Uses free ip-api.com (no key) server-side. Throttled to limit egress abuse.
    """
    try:
        ip = _client_ip(request)
        params = {'fields': 'status,message,city,regionName,zip'}
        # Private/local IPs: let provider resolve via this server's egress IP
        if ip and _is_public_ip(ip):
            url = f'http://ip-api.com/json/{ip}'
        else:
            url = 'http://ip-api.com/json/'
        resp = requests.get(url, params=params, timeout=3)
        data = resp.json() if resp.ok else {}
        if data.get('status') != 'success':
            return Response(
                {'city': None, 'state': None, 'pincode': None},
                status=status.HTTP_200_OK
            )
        return Response(
            {
                'city': data.get('city') or None,
                'state': data.get('regionName') or None,
                'pincode': data.get('zip') or None,
            },
            status=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Error estimating geo from IP: {str(e)}")
        return Response(
            {'city': None, 'state': None, 'pincode': None},
            status=status.HTTP_200_OK
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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET', 'POST', 'PUT', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def update_operating_hours(request):
    """
    Get or update retailer operating hours - only for retailer users
    """
    try:
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access operating hours'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            profile = RetailerProfile.objects.get(user=request.user)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Retailer profile not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
            
        if request.method == 'GET':
            hours = RetailerOperatingHours.objects.filter(retailer=profile).order_by('id')
            serializer = RetailerOperatingHoursSerializer(hours, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
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
            {'error': format_exception(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _caller_profile_or_error(request):
    """Return (profile, error_response). error_response is set on authz failure."""
    if request.user.user_type != 'retailer':
        return None, Response(
            {'error': 'Only retailers can access organization endpoints'},
            status=status.HTTP_403_FORBIDDEN,
        )
    try:
        profile = RetailerProfile.objects.select_related('organization').get(
            user=request.user
        )
    except RetailerProfile.DoesNotExist:
        return None, Response(
            {'error': 'Retailer profile not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return profile, None


def _resolve_org_for_caller(request, org_id):
    """
    Same-tenant org resolution for profile owners and staff members.

    Cross-tenant / missing → 403 without leaking existence.
    Does not create orgs on the deny path.
    """
    if request.user.user_type != 'retailer':
        return None, Response(
            {'error': 'Only retailers can access organization endpoints'},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        org = Organization.objects.get(pk=org_id)
    except Organization.DoesNotExist:
        return None, Response(
            {'error': 'Organization not found or access denied'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not user_belongs_to_organization(request.user, org):
        return None, Response(
            {'error': 'Organization not found or access denied'},
            status=status.HTTP_403_FORBIDDEN,
        )

    ensure_org_rbac_bootstrap(org)
    return org, None


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def organization_me(request):
    """
    GET  — caller's organization (implicit 1:1 for single-shop tenants).
    POST — create an org and attach the existing shop as location 1 (staff-admin).
    """
    try:
        profile, err = _caller_profile_or_error(request)
        if err is not None:
            return err

        if request.method == 'GET':
            org = profile.organization
            if org is None:
                org = ensure_organization_for_profile(profile)
            else:
                ensure_org_rbac_bootstrap(org)
            return Response(
                OrganizationSerializer(org).data,
                status=status.HTTP_200_OK,
            )

        # POST — create org + attach shop as location 1
        create_ser = OrganizationCreateSerializer(data=request.data)
        if not create_ser.is_valid():
            return Response(create_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        if profile.organization_id:
            if not user_is_org_staff_admin(request.user, profile.organization):
                return Response(
                    {'error': 'Organization staff-admin permission required'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response(
                {'error': 'Organization already exists for this shop'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = create_ser.validated_data.get('name') or None
        org = ensure_organization_for_profile(profile, name=name)
        logger.info("Organization created: %s (location=%s)", org.name, profile.pk)
        return Response(
            OrganizationSerializer(org).data,
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        logger.error(f"Error in organization_me: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def organization_detail(request, org_id):
    """
    GET/PATCH a specific organization.

    Cross-tenant: callers may only access their own org; others get 403
    and the resource is unchanged. PATCH requires ``org.update``.
    """
    try:
        # Isolation only — do not ensure/create org on a deny path
        if request.user.user_type != 'retailer':
            return Response(
                {'error': 'Only retailers can access organization endpoints'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            org = Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist:
            return Response(
                {'error': 'Organization not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not user_belongs_to_organization(request.user, org):
            return Response(
                {'error': 'Organization not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ensure_org_rbac_bootstrap(org)

        if request.method == 'GET':
            return Response(
                OrganizationSerializer(org).data,
                status=status.HTTP_200_OK,
            )

        # PATCH — requires org.update; refuse without mutating
        if not user_has_org_permission(request.user, org, 'org.update'):
            return Response(
                {'error': 'Organization update permission required'},
                status=status.HTTP_403_FORBIDDEN,
            )

        update_ser = OrganizationUpdateSerializer(
            org, data=request.data, partial=True
        )
        if not update_ser.is_valid():
            return Response(update_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        org = update_ser.save()
        logger.info("Organization updated: %s (active=%s)", org.pk, org.is_active)
        return Response(
            OrganizationSerializer(org).data,
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.error(f"Error in organization_detail: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def organization_permission_catalog(request, org_id):
    """Versioned permission catalog for this org (same-tenant read)."""
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err
        return Response(catalog_payload(), status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in organization_permission_catalog: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def organization_roles(request, org_id):
    """
    List or create named roles for an organization.

    POST requires ``roles.manage``. Unknown permission codes → 400.
    """
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err

        if request.method == 'GET':
            roles = OrgRole.objects.filter(organization=org).order_by('slug')
            return Response(
                OrgRoleSerializer(roles, many=True).data,
                status=status.HTTP_200_OK,
            )

        if not user_has_org_permission(request.user, org, 'roles.manage'):
            return Response(
                {'error': 'Role manage permission required'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = OrgRoleCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        slug = ser.validated_data['slug']
        if OrgRole.objects.filter(organization=org, slug=slug).exists():
            return Response(
                {'error': 'Role slug already exists'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = OrgRole.objects.create(
            organization=org,
            name=ser.validated_data['name'],
            slug=slug,
            permissions=ser.validated_data.get('permissions') or [],
            is_system=False,
        )
        return Response(
            OrgRoleSerializer(role).data,
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        logger.error(f"Error in organization_roles: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'PATCH'])
@permission_classes([permissions.IsAuthenticated])
def organization_role_detail(request, org_id, role_id):
    """Get or update a named role. PATCH requires ``roles.manage``."""
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err

        try:
            role = OrgRole.objects.get(pk=role_id, organization=org)
        except OrgRole.DoesNotExist:
            return Response(
                {'error': 'Role not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'GET':
            return Response(OrgRoleSerializer(role).data, status=status.HTTP_200_OK)

        if not user_has_org_permission(request.user, org, 'roles.manage'):
            return Response(
                {'error': 'Role manage permission required'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = OrgRoleUpdateSerializer(data=request.data, partial=True)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        # System admin role must retain full catalog (owner bootstrap)
        if role.slug == ROLE_SLUG_ADMIN and 'permissions' in ser.validated_data:
            new_perms = set(ser.validated_data['permissions'])
            if not ALL_PERMISSION_CODES.issubset(new_perms):
                return Response(
                    {'error': 'Admin role must retain all catalog permissions'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if 'name' in ser.validated_data:
            role.name = ser.validated_data['name']
        if 'permissions' in ser.validated_data:
            role.permissions = ser.validated_data['permissions']
        role.save()
        return Response(OrgRoleSerializer(role).data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in organization_role_detail: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def organization_staff(request, org_id):
    """
    List staff memberships or assign a user to a named role.

    POST requires ``staff.manage``. Creates AUTH_USER_MODEL retailer users
    for new cashiers (password auth — not customer OTP).
    """
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err

        if request.method == 'GET':
            if not (
                user_has_org_permission(request.user, org, 'staff.manage')
                or user_belongs_to_organization(request.user, org)
            ):
                return Response(
                    {'error': 'Organization not found or access denied'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            # Same-tenant members can list; deny-by-default already applied
            memberships = (
                OrgStaffMembership.objects.select_related('user', 'role')
                .filter(organization=org)
                .order_by('id')
            )
            return Response(
                OrgStaffMembershipSerializer(memberships, many=True).data,
                status=status.HTTP_200_OK,
            )

        if not user_has_org_permission(request.user, org, 'staff.manage'):
            return Response(
                {'error': 'Staff manage permission required'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = OrgStaffAssignSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            role = OrgRole.objects.get(
                pk=ser.validated_data['role_id'],
                organization=org,
            )
        except OrgRole.DoesNotExist:
            return Response(
                {'error': 'Role not found in this organization'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            user_id = ser.validated_data.get('user_id')
            if user_id:
                try:
                    staff_user = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    return Response(
                        {'error': 'User not found'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if staff_user.user_type != 'retailer':
                    return Response(
                        {'error': 'Staff users must be retailer-type AUTH_USER_MODEL rows'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                username = ser.validated_data['username']
                if User.objects.filter(username=username).exists():
                    return Response(
                        {'error': 'Username already taken'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                staff_user = User.objects.create_user(
                    username=username,
                    email=ser.validated_data.get('email') or '',
                    password=ser.validated_data['password'],
                    user_type='retailer',
                    is_active=True,
                )

            existing = OrgStaffMembership.objects.filter(
                organization=org, user=staff_user
            ).select_related('role').first()

            if existing:
                if would_remove_last_owner(
                    org, target_user=staff_user, new_role=role
                ):
                    return Response(
                        {'error': 'Cannot remove the last owner'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                from_role = existing.role
                action = (
                    OrgStaffRoleAudit.ACTION_CHANGE
                    if from_role.id != role.id
                    else OrgStaffRoleAudit.ACTION_GRANT
                )
                existing.role = role
                existing.is_active = True
                existing.save(update_fields=['role', 'is_active', 'updated_at'])
                membership = existing
                record_staff_role_audit(
                    organization=org,
                    actor=request.user,
                    target_user=staff_user,
                    action=action,
                    from_role=from_role,
                    to_role=role,
                )
            else:
                membership = OrgStaffMembership.objects.create(
                    organization=org,
                    user=staff_user,
                    role=role,
                    is_active=True,
                )
                record_staff_role_audit(
                    organization=org,
                    actor=request.user,
                    target_user=staff_user,
                    action=OrgStaffRoleAudit.ACTION_GRANT,
                    from_role=None,
                    to_role=role,
                )

        membership = (
            OrgStaffMembership.objects.select_related('user', 'role')
            .get(pk=membership.pk)
        )
        return Response(
            OrgStaffMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        logger.error(f"Error in organization_staff: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def organization_staff_detail(request, org_id, membership_id):
    """
    Get / change / revoke a staff membership.

    Mutations require ``staff.manage``. 403 leaves the membership unchanged.
    Unauthorized users cannot change another user's role.
    """
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err

        try:
            membership = (
                OrgStaffMembership.objects.select_related('user', 'role')
                .get(pk=membership_id, organization=org)
            )
        except OrgStaffMembership.DoesNotExist:
            return Response(
                {'error': 'Staff membership not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'GET':
            return Response(
                OrgStaffMembershipSerializer(membership).data,
                status=status.HTTP_200_OK,
            )

        if not user_has_org_permission(request.user, org, 'staff.manage'):
            return Response(
                {'error': 'Staff manage permission required'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'DELETE':
            if would_remove_last_owner(
                org, target_user=membership.user, deactivate=True
            ):
                return Response(
                    {'error': 'Cannot remove the last owner'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            from_role = membership.role
            target = membership.user
            membership.is_active = False
            membership.save(update_fields=['is_active', 'updated_at'])
            record_staff_role_audit(
                organization=org,
                actor=request.user,
                target_user=target,
                action=OrgStaffRoleAudit.ACTION_REVOKE,
                from_role=from_role,
                to_role=None,
            )
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PATCH
        ser = OrgStaffUpdateSerializer(data=request.data, partial=True)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        new_role = membership.role
        if 'role_id' in ser.validated_data:
            try:
                new_role = OrgRole.objects.get(
                    pk=ser.validated_data['role_id'],
                    organization=org,
                )
            except OrgRole.DoesNotExist:
                return Response(
                    {'error': 'Role not found in this organization'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        deactivate = (
            'is_active' in ser.validated_data
            and ser.validated_data['is_active'] is False
        )
        if would_remove_last_owner(
            org,
            target_user=membership.user,
            new_role=new_role if 'role_id' in ser.validated_data else None,
            deactivate=deactivate,
        ):
            return Response(
                {'error': 'Cannot remove the last owner'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_role = membership.role
        updates = []
        action = None
        if 'role_id' in ser.validated_data and new_role.id != membership.role_id:
            membership.role = new_role
            updates.append('role')
            action = OrgStaffRoleAudit.ACTION_CHANGE
        if 'is_active' in ser.validated_data:
            membership.is_active = ser.validated_data['is_active']
            updates.append('is_active')
            if deactivate:
                action = OrgStaffRoleAudit.ACTION_REVOKE
            elif ser.validated_data['is_active'] and action is None:
                action = OrgStaffRoleAudit.ACTION_GRANT

        if updates:
            updates.append('updated_at')
            membership.save(update_fields=updates)
            if action:
                record_staff_role_audit(
                    organization=org,
                    actor=request.user,
                    target_user=membership.user,
                    action=action,
                    from_role=from_role,
                    to_role=(
                        membership.role
                        if action != OrgStaffRoleAudit.ACTION_REVOKE
                        else None
                    ),
                )

        membership = (
            OrgStaffMembership.objects.select_related('user', 'role')
            .get(pk=membership.pk)
        )
        return Response(
            OrgStaffMembershipSerializer(membership).data,
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Error in organization_staff_detail: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def organization_api_scope_catalog(request, org_id):
    """Versioned partner API scope catalog (same-tenant JWT read)."""
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err
        return Response(scope_catalog_payload(), status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in organization_api_scope_catalog: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def organization_api_keys(request, org_id):
    """
    List or create org-scoped partner API keys (JWT / staff).

    POST requires ``api_keys.manage``. Raw secret is returned once on create.
    """
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err

        if request.method == 'GET':
            if not user_has_org_permission(request.user, org, 'api_keys.manage'):
                return Response(
                    {'error': 'API key management permission required'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            keys = OrgApiKey.objects.filter(organization=org).order_by('-created_at')
            return Response(
                OrgApiKeySerializer(keys, many=True).data,
                status=status.HTTP_200_OK,
            )

        if not user_has_org_permission(request.user, org, 'api_keys.manage'):
            return Response(
                {'error': 'API key management permission required'},
                status=status.HTTP_403_FORBIDDEN,
            )

        create_ser = OrgApiKeyCreateSerializer(data=request.data)
        if not create_ser.is_valid():
            return Response(create_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        api_key, raw = create_org_api_key(
            organization=org,
            name=create_ser.validated_data['name'],
            scopes=create_ser.validated_data.get('scopes') or [],
            created_by=request.user,
        )
        payload = OrgApiKeySerializer(api_key).data
        payload['api_key'] = raw  # shown once
        return Response(payload, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.error(f"Error in organization_api_keys: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def organization_api_key_detail(request, org_id, key_id):
    """
    Read / update scopes / revoke an org API key.

    Mutations require ``api_keys.manage``. DELETE soft-revokes (next request 401).
    Cross-tenant key ids return 403 without mutating.
    """
    try:
        org, err = _resolve_org_for_caller(request, org_id)
        if err is not None:
            return err

        if not user_has_org_permission(request.user, org, 'api_keys.manage'):
            return Response(
                {'error': 'API key management permission required'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            api_key = OrgApiKey.objects.get(pk=key_id, organization=org)
        except OrgApiKey.DoesNotExist:
            return Response(
                {'error': 'API key not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == 'GET':
            return Response(
                OrgApiKeySerializer(api_key).data,
                status=status.HTTP_200_OK,
            )

        if request.method == 'DELETE':
            revoke_org_api_key(api_key=api_key, actor=request.user)
            api_key.refresh_from_db()
            return Response(
                OrgApiKeySerializer(api_key).data,
                status=status.HTTP_200_OK,
            )

        # PATCH — name and/or scopes
        update_ser = OrgApiKeyUpdateSerializer(data=request.data, partial=True)
        if not update_ser.is_valid():
            return Response(update_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        data = update_ser.validated_data
        if 'name' in data:
            api_key.name = data['name']
            api_key.save(update_fields=['name', 'updated_at'])
        if 'scopes' in data:
            update_org_api_key_scopes(
                api_key=api_key,
                scopes=data['scopes'],
                actor=request.user,
            )
            api_key.refresh_from_db()

        return Response(
            OrgApiKeySerializer(api_key).data,
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Error in organization_api_key_detail: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
