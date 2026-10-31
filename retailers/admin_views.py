import logging
from django.conf import settings
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404
from rest_framework.pagination import PageNumberPagination
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import RetailerProfile, RetailerVerificationDocument
from .verification import TransitionError, apply_admin_action, refresh_checks

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


def _profile_row(profile, with_checks=False):
    user = profile.user
    row = {
        'id': profile.id,
        'user_id': user.id if user else None,
        'username': user.username if user else '',
        'email': user.email if user else '',
        'phone_number': user.phone_number if user else '',
        'is_phone_verified': bool(user and user.is_phone_verified),
        'first_name': user.first_name if user else '',
        'last_name': user.last_name if user else '',
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
        'submitted_at': profile.verification_submitted_at,
        'review_needed': profile.verification_review_needed,
        'created_at': profile.created_at,
    }
    if with_checks:
        # Stored result from the last submit/review; no recompute on the list.
        stored = profile.verification_checks or {}
        row['check_counts'] = stored.get('counts')
        row['checks_ran_at'] = stored.get('ran_at')
    return row


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
    if status_filter not in valid_statuses | {'all', 'review_needed'}:
        return Response(
            {'error': "Invalid status. Must be one of: " + ', '.join(sorted(valid_statuses | {'all', 'review_needed'})) + '.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    search_query = request.GET.get('search', '').strip()

    queryset = RetailerProfile.objects.select_related('user').all()

    if status_filter == 'review_needed':
        queryset = queryset.filter(verification_review_needed=True)
    elif status_filter != 'all':
        queryset = queryset.filter(verification_status=status_filter)

    if search_query:
        queryset = queryset.filter(
            Q(shop_name__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__phone_number__icontains=search_query) |
            Q(city__icontains=search_query)
        )

    if status_filter == 'pending':
        # Submitted shops first (oldest submission first), then unsubmitted signups.
        queryset = queryset.order_by(
            F('verification_submitted_at').asc(nulls_last=True), '-created_at',
        )
    else:
        queryset = queryset.order_by('-created_at')

    # Status counts for admin tab badges (single aggregate query)
    counts = RetailerProfile.objects.aggregate(
        pending=Count('id', filter=Q(verification_status='pending')),
        approved=Count('id', filter=Q(verification_status='approved')),
        rejected=Count('id', filter=Q(verification_status='rejected')),
        needs_changes=Count('id', filter=Q(verification_status='needs_changes')),
        suspended=Count('id', filter=Q(verification_status='suspended')),
        review_needed=Count('id', filter=Q(verification_review_needed=True)),
        all=Count('id'),
    )

    paginator = PageNumberPagination()
    paginator.page_size = 50
    paginator.page_size_query_param = 'page_size'
    paginator.max_page_size = 200
    page = paginator.paginate_queryset(queryset, request)

    results = [_profile_row(p, with_checks=True) for p in page]

    paged = paginator.get_paginated_response(results).data
    return Response({'counts': counts, **paged}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsPlatformAdmin])
def verify_retailer_action(request, profile_id):
    """
    Change a retailer's verification status.
    Payload:
      - action: approve | request_changes | reject | suspend | reinstate | mark_reviewed
      - reason: required for request_changes and suspend; optional otherwise
    Every action writes a VerificationEvent (who, when, why).
    """
    if not RetailerProfile.objects.filter(pk=profile_id).exists():
        return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)

    action = request.data.get('action')
    reason = request.data.get('reason')
    action = action.strip().lower() if isinstance(action, str) else ''
    reason = reason.strip() if isinstance(reason, str) else ''

    try:
        profile = apply_admin_action(profile_id, action, request.user, reason)
    except TransitionError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    logger.info(
        "Admin %s %s retailer profile %s (%s)", request.user.pk, action, profile.id, profile.shop_name,
    )
    messages = {
        'approve': f"Retailer '{profile.shop_name}' approved successfully.",
        'request_changes': f"Asked '{profile.shop_name}' for changes.",
        'reject': f"Retailer '{profile.shop_name}' rejected.",
        'suspend': f"Retailer '{profile.shop_name}' suspended.",
        'reinstate': f"Retailer '{profile.shop_name}' reinstated.",
        'mark_reviewed': f"Changes on '{profile.shop_name}' marked as reviewed.",
    }
    return Response({
        'message': messages[action],
        'verification_status': profile.verification_status,
        'is_verified': profile.is_verified,
        'rejection_reason': profile.rejection_reason or '',
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsPlatformAdmin])
def retailer_verification_detail(request, profile_id):
    """Full review page data: profile, fresh automated checks, documents, audit log."""
    try:
        profile = RetailerProfile.objects.select_related('user').get(pk=profile_id)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)

    data = refresh_checks(profile)
    events = profile.verification_events.select_related('actor')[:50]
    docs = profile.verification_documents.all()[:20]
    return Response({
        **_profile_row(profile),
        'shop_image': profile.shop_image.url if profile.shop_image else None,
        'latitude': profile.latitude,
        'longitude': profile.longitude,
        'upi_id': profile.upi_id,
        'proof_type': profile.proof_type,
        'proof_number': profile.proof_number,
        **data,
        'documents': [
            {
                'id': d.id,
                'kind': d.kind,
                'content_type': d.content_type,
                'uploaded_at': d.uploaded_at,
                'url': f'/api/retailer/admin/verifications/{profile.id}/documents/{d.id}/',
            }
            for d in docs
        ],
        'events': [
            {
                'id': e.id,
                'action': e.action,
                'from_status': e.from_status,
                'to_status': e.to_status,
                'reason': e.reason,
                'details': e.details,
                'actor': (e.actor.email or e.actor.username) if e.actor else None,
                'created_at': e.created_at,
            }
            for e in events
        ],
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsPlatformAdmin])
def retailer_verification_document(request, profile_id, doc_id):
    """Stream a private verification document to a platform admin."""
    try:
        doc = RetailerVerificationDocument.objects.get(pk=doc_id, retailer_id=profile_id)
    except RetailerVerificationDocument.DoesNotExist:
        raise Http404
    try:
        handle = doc.file.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(handle, content_type=doc.content_type or 'application/octet-stream')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
