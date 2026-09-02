"""
Versioned partner API views (OE-182 / F-0006).

Key-authenticated only. JWT retailer/customer apps keep /api/retailer/ and
/api/customer/. Breaking changes go to /api/v2/; v1 remains until sunset.
"""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from common.authentication import OrgApiKeyAuthentication, get_request_api_key
from common.api_key_permissions import HasApiKeyScope, require_api_scope
from common.error_utils import format_exception
from common.throttling import OrgApiKeyRateThrottle

from .api_scopes import scope_catalog_payload
from .models import RetailerProfile
from .serializers import (
    PartnerLocationSerializer,
    PartnerOrganizationSerializer,
    PartnerOrgUpdateSerializer,
)

logger = logging.getLogger(__name__)

_PARTNER_AUTH = [OrgApiKeyAuthentication]
_PARTNER_THROTTLE = [OrgApiKeyRateThrottle]


class _IsAuthenticatedApiKey(BasePermission):
    """Any valid (non-revoked) org API key."""

    def has_permission(self, request, view):
        api_key = get_request_api_key(request)
        if api_key is None:
            return False
        api_key.refresh_from_db(fields=['is_active'])
        return bool(api_key.is_active)


class _PartnerOrgViewScope(HasApiKeyScope):
    """GET requires partner.org.read; PATCH requires partner.org.write."""

    def has_permission(self, request, view):
        if request.method == 'PATCH':
            self.required_scope = 'partner.org.write'
        else:
            self.required_scope = 'partner.org.read'
        return super().has_permission(request, view)


def _partner_org_or_401(request):
    api_key = get_request_api_key(request)
    if api_key is None:
        return None, Response(
            {'error': 'Authentication credentials were not provided.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    api_key.refresh_from_db(fields=['is_active', 'scopes'])
    if not api_key.is_active:
        return None, Response(
            {'error': 'Invalid or revoked API key'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    return api_key.organization, None


@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def api_version_info(request):
    """
    Public version policy for retailer/customer/partner surfaces.

    Documents that v1 remains until an explicit sunset; breaking changes
    use a new prefix.
    """
    policy = getattr(settings, 'API_VERSIONING', {})
    return Response(
        {
            'current': policy.get('current', 'v1'),
            'supported': policy.get('supported', ['v1']),
            'sunset': policy.get('sunset', {'v1': None}),
            'notes': policy.get('notes', ''),
            'surfaces': {
                'partner': '/api/v1/partner/',
                'retailer_jwt': [
                    '/api/retailer/',
                    '/api/v1/retailer/',
                ],
                'customer_jwt': [
                    '/api/customer/',
                    '/api/v1/customer/',
                ],
            },
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@authentication_classes(_PARTNER_AUTH)
@permission_classes([_IsAuthenticatedApiKey])
@throttle_classes(_PARTNER_THROTTLE)
def partner_scope_catalog(request):
    """Versioned partner scope catalog for authenticated API keys."""
    try:
        return Response(scope_catalog_payload(), status=status.HTTP_200_OK)
    except Exception as e:
        logger.error("partner_scope_catalog: %s", e)
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'PATCH'])
@authentication_classes(_PARTNER_AUTH)
@permission_classes([_PartnerOrgViewScope])
@throttle_classes(_PARTNER_THROTTLE)
def partner_organization(request):
    """
    Read/update the organization bound to the API key.

    GET → partner.org.read; PATCH → partner.org.write.
    Missing scope → 403 and the resource is unchanged.
    """
    try:
        org, err = _partner_org_or_401(request)
        if err is not None:
            return err

        if request.method == 'GET':
            return Response(
                PartnerOrganizationSerializer(org).data,
                status=status.HTTP_200_OK,
            )

        original_name = org.name
        ser = PartnerOrgUpdateSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        new_name = ser.validated_data['name'].strip()
        if not new_name:
            return Response(
                {'name': ['This field may not be blank.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        org.name = new_name
        org.save(update_fields=['name', 'updated_at'])
        logger.info(
            "Partner org rename %s: %r -> %r",
            org.pk, original_name, org.name,
        )
        return Response(
            PartnerOrganizationSerializer(org).data,
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("partner_organization: %s", e)
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
@authentication_classes(_PARTNER_AUTH)
@permission_classes([require_api_scope('partner.locations.read')])
@throttle_classes(_PARTNER_THROTTLE)
def partner_locations(request):
    """List shop locations for the key's organization only."""
    try:
        org, err = _partner_org_or_401(request)
        if err is not None:
            return err

        locations = org.locations.filter(is_active=True).order_by('id')
        return Response(
            PartnerLocationSerializer(locations, many=True).data,
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("partner_locations: %s", e)
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
@authentication_classes(_PARTNER_AUTH)
@permission_classes([require_api_scope('partner.locations.read')])
@throttle_classes(_PARTNER_THROTTLE)
def partner_location_detail(request, location_id):
    """
    Read one location belonging to the key's org.

    Cross-tenant: a location id from org B returns 403 (not disclosed).
    """
    try:
        org, err = _partner_org_or_401(request)
        if err is not None:
            return err

        try:
            location = RetailerProfile.objects.get(pk=location_id)
        except RetailerProfile.DoesNotExist:
            return Response(
                {'error': 'Location not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if location.organization_id != org.id:
            return Response(
                {'error': 'Location not found or access denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            PartnerLocationSerializer(location).data,
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("partner_location_detail: %s", e)
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
