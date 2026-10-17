import logging
from django.conf import settings
from django.db.models import Count, Q
from rest_framework.pagination import PageNumberPagination
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import RetailerProfile

logger = logging.getLogger(__name__)


class IsPlatformAdmin(permissions.BasePermission):
    """
    Allows access only to platform administrators (either is_staff/superuser
    or user whose email is in settings.ADMIN_EMAILS).
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        admin_emails = getattr(settings, 'ADMIN_EMAILS', [])
        user_email = (request.user.email or '').strip().lower()
        return bool(
            request.user.is_staff
            or request.user.is_superuser
            or (user_email and user_email in admin_emails)
        )


@api_view(['GET'])
@permission_classes([IsPlatformAdmin])
def list_retailer_verifications(request):
    """
    List retailers for admin verification.
    Query params:
      - status: 'pending' (default), 'approved', 'rejected', 'all'
      - search: string to match shop_name, username, email, phone, city
    """
    status_filter = request.GET.get('status', 'pending').strip().lower()
    valid_statuses = {choice for choice, _ in RetailerProfile.VERIFICATION_STATUS_CHOICES}
    if status_filter != 'all' and status_filter not in valid_statuses:
        return Response(
            {'error': "Invalid status. Must be 'pending', 'approved', 'rejected' or 'all'."},
            status=status.HTTP_400_BAD_REQUEST
        )
    search_query = request.GET.get('search', '').strip()

    queryset = RetailerProfile.objects.select_related('user').all()

    if status_filter != 'all':
        queryset = queryset.filter(verification_status=status_filter)

    if search_query:
        queryset = queryset.filter(
            Q(shop_name__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__phone_number__icontains=search_query) |
            Q(city__icontains=search_query)
        )

    queryset = queryset.order_by('-created_at')

    # Status counts for admin tab badges (single aggregate query)
    counts = RetailerProfile.objects.aggregate(
        pending=Count('id', filter=Q(verification_status='pending')),
        approved=Count('id', filter=Q(verification_status='approved')),
        rejected=Count('id', filter=Q(verification_status='rejected')),
        all=Count('id'),
    )

    paginator = PageNumberPagination()
    paginator.page_size = 50
    paginator.page_size_query_param = 'page_size'
    paginator.max_page_size = 200
    page = paginator.paginate_queryset(queryset, request)

    results = []
    for profile in page:
        results.append({
            'id': profile.id,
            'user_id': profile.user.id if profile.user else None,
            'username': profile.user.username if profile.user else '',
            'email': profile.user.email if profile.user else '',
            'phone_number': profile.user.phone_number if profile.user else '',
            'first_name': profile.user.first_name if profile.user else '',
            'last_name': profile.user.last_name if profile.user else '',
            'shop_name': profile.shop_name,
            'shop_description': profile.shop_description,
            'shop_image': profile.shop_image.url if profile.shop_image else None,
            'contact_email': profile.contact_email,
            'contact_phone': profile.contact_phone,
            'address_line1': profile.address_line1,
            'address_line2': profile.address_line2,
            'city': profile.city,
            'state': profile.state,
            'pincode': profile.pincode,
            'business_type': profile.business_type,
            'gst_number': profile.gst_number,
            'pan_number': profile.pan_number,
            'is_verified': profile.is_verified,
            'verification_status': profile.verification_status,
            'rejection_reason': profile.rejection_reason or '',
            'is_active': profile.is_active,
            'created_at': profile.created_at,
        })

    paged = paginator.get_paginated_response(results).data
    return Response({'counts': counts, **paged}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsPlatformAdmin])
def verify_retailer_action(request, profile_id):
    """
    Approve or reject a retailer verification request.
    Payload:
      - action: 'approve' or 'reject'
      - reason: string (optional for approve, required/recommended for reject)
    """
    try:
        profile = RetailerProfile.objects.select_related('user').get(pk=profile_id)
    except RetailerProfile.DoesNotExist:
        return Response(
            {'error': 'Retailer profile not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    action = request.data.get('action')
    reason = request.data.get('reason')
    action = action.strip().lower() if isinstance(action, str) else ''
    reason = reason.strip() if isinstance(reason, str) else ''

    previous_status = profile.verification_status

    if action == 'approve':
        profile.verification_status = 'approved'
        profile.is_verified = True
        # Only a first-time/rejected retailer is switched on; a shop that was
        # already approved keeps whatever active state the retailer chose.
        if previous_status != 'approved':
            profile.is_active = True
        profile.rejection_reason = ''
        profile.save(update_fields=['verification_status', 'is_verified', 'is_active', 'rejection_reason', 'updated_at'])
        logger.info(f"Admin approved retailer profile {profile.id} ({profile.shop_name})")
        return Response({
            'message': f"Retailer '{profile.shop_name}' approved successfully.",
            'verification_status': 'approved',
            'is_verified': True,
        }, status=status.HTTP_200_OK)

    elif action == 'reject':
        if not reason:
            reason = 'Verification rejected by administrator.'
        profile.verification_status = 'rejected'
        profile.is_verified = False
        profile.is_active = False
        profile.rejection_reason = reason
        profile.save(update_fields=['verification_status', 'is_verified', 'is_active', 'rejection_reason', 'updated_at'])
        logger.info(f"Admin rejected retailer profile {profile.id} ({profile.shop_name}): {reason}")
        return Response({
            'message': f"Retailer '{profile.shop_name}' rejected.",
            'verification_status': 'rejected',
            'is_verified': False,
            'rejection_reason': reason,
        }, status=status.HTTP_200_OK)

    else:
        return Response(
            {'error': "Invalid action. Must be 'approve' or 'reject'."},
            status=status.HTTP_400_BAD_REQUEST
        )
