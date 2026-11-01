"""Retailer-facing verification endpoints (onboarding checklist)."""
import logging

from rest_framework import permissions, status
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .models import RetailerProfile, RetailerVerificationDocument
from .verification import TransitionError, retailer_payload, submit_for_review

logger = logging.getLogger(__name__)

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
ALLOWED_DOCUMENT_TYPES = {
    'image/jpeg': b'\xff\xd8\xff',
    'image/png': b'\x89PNG',
    'image/webp': b'RIFF',
    'application/pdf': b'%PDF',
}


class DocumentUploadThrottle(UserRateThrottle):
    # Own scope, so the cache key is not shared with the global per-user
    # throttle (which records every request the user makes).
    scope = 'verification_documents'
    rate = '30/hour'


def _owner_profile(request):
    if getattr(request.user, 'user_type', None) != 'retailer':
        return None
    return RetailerProfile.objects.select_related('user').filter(user=request.user).first()


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def verification_status(request):
    """Checklist for the shop owner: status, reason, steps and check results."""
    profile = _owner_profile(request)
    if profile is None:
        return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response(retailer_payload(profile))


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def submit_verification(request):
    """Send the shop to the admin queue once every blocking check passes."""
    profile = _owner_profile(request)
    if profile is None:
        return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
    try:
        ok, _data = submit_for_review(profile, request.user)
    except TransitionError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    payload = retailer_payload(profile)
    if not ok:
        return Response({'error': 'Finish the remaining steps first.', **payload},
                        status=status.HTTP_400_BAD_REQUEST)
    logger.info("Retailer %s submitted shop %s for verification", request.user.pk, profile.pk)
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@throttle_classes([DocumentUploadThrottle])
def upload_verification_document(request):
    """Upload a private document: kind = proof | owner_id | selfie, file = image or PDF (5 MB)."""
    profile = _owner_profile(request)
    if profile is None:
        return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)

    kind = (request.data.get('kind') or '').strip()
    valid_kinds = {k for k, _ in RetailerVerificationDocument.KIND_CHOICES}
    if kind not in valid_kinds:
        return Response({'kind': [f"Must be one of: {', '.join(sorted(valid_kinds))}."]},
                        status=status.HTTP_400_BAD_REQUEST)
    upload = request.FILES.get('file')
    if upload is None:
        return Response({'file': ['Attach a file.']}, status=status.HTTP_400_BAD_REQUEST)
    if upload.size > MAX_DOCUMENT_BYTES:
        return Response({'file': ['File must be 5 MB or smaller.']}, status=status.HTTP_400_BAD_REQUEST)
    # Trust the bytes, not the client's content type.
    head = upload.read(16)
    upload.seek(0)
    content_type = next((ct for ct, magic in ALLOWED_DOCUMENT_TYPES.items() if head.startswith(magic)), None)
    if content_type == 'image/webp' and head[8:12] != b'WEBP':
        content_type = None
    if content_type is None:
        return Response({'file': ['Upload a JPG, PNG, WEBP or PDF.']}, status=status.HTTP_400_BAD_REQUEST)

    doc = RetailerVerificationDocument.objects.create(
        retailer=profile, kind=kind, file=upload, content_type=content_type,
    )
    # Keep only the latest file per kind.
    for old in RetailerVerificationDocument.objects.filter(retailer=profile, kind=kind).exclude(pk=doc.pk):
        old.file.delete(save=False)
        old.delete()
    return Response(retailer_payload(profile), status=status.HTTP_201_CREATED)
