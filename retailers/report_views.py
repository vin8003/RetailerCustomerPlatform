"""Customer reports and admin moderation endpoints."""
import logging

from django.db.models import Count, Max, Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .admin_views import IsPlatformAdmin
from .models import CustomerReport, RetailerProfile
from .reports import PRODUCT_FLAG_REPORTERS, SHOP_FLAG_REPORTERS, file_report, handle_reports, strikes_in_window
from .verification import TransitionError

logger = logging.getLogger(__name__)


class ReportThrottle(UserRateThrottle):
    scope = 'customer_reports'
    rate = '20/day'


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ReportThrottle])
def report_retailer(request, retailer_id):
    """Customer reports a shop, or one of its products with product_id."""
    from products.models import Product

    retailer = RetailerProfile.objects.public().filter(pk=retailer_id).first()
    if retailer is None:
        return Response({'error': 'Shop not found'}, status=status.HTTP_404_NOT_FOUND)
    if retailer.user_id == request.user.id:
        return Response({'error': 'You cannot report your own shop.'}, status=status.HTTP_400_BAD_REQUEST)

    reason = (request.data.get('reason') or '').strip()
    valid = {k for k, _ in CustomerReport.REASON_CHOICES}
    if reason not in valid:
        return Response({'reason': [f"Must be one of: {', '.join(sorted(valid))}."]}, status=status.HTTP_400_BAD_REQUEST)
    text = request.data.get('text') or ''
    if not isinstance(text, str) or len(text) > 1000:
        return Response({'text': ['At most 1000 characters.']}, status=status.HTTP_400_BAD_REQUEST)

    product = None
    product_id = request.data.get('product_id')
    if product_id not in (None, ''):
        try:
            product = Product.objects.get(pk=int(product_id), retailer=retailer)
        except (TypeError, ValueError, Product.DoesNotExist):
            return Response({'product_id': ['Product not found in this shop.']}, status=status.HTTP_400_BAD_REQUEST)

    report, created = file_report(retailer=retailer, product=product, reporter=request.user, reason=reason, text=text)
    return Response(
        {
            'id': report.id,
            'created': created,
            'message': 'Thanks. Our team will look into it.' if created else 'You already reported this. Our team will look into it.',
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([IsPlatformAdmin])
def admin_report_inbox(request):
    """Open reports grouped by target (shop or product), most-reported first."""
    status_filter = request.GET.get('status', 'open')
    if status_filter not in ('open', 'actioned', 'dismissed'):
        return Response({'error': "status must be open, actioned or dismissed"}, status=status.HTTP_400_BAD_REQUEST)
    groups = (
        CustomerReport.objects.filter(status=status_filter)
        .values('retailer_id', 'product_id')
        .annotate(
            reports=Count('id'),
            reporters=Count('reporter_id', distinct=True),
            latest=Max('created_at'),
        )
        .order_by('-reporters', '-latest')
    )
    paginator = PageNumberPagination()
    paginator.page_size = 50
    page = paginator.paginate_queryset(groups, request)

    from products.models import Product
    shop_ids = {g['retailer_id'] for g in page}
    product_ids = {g['product_id'] for g in page if g['product_id']}
    shops = {s.id: s for s in RetailerProfile.objects.filter(id__in=shop_ids)}
    products = {p.id: p for p in Product.objects.filter(id__in=product_ids)}

    results = []
    for g in page:
        shop = shops.get(g['retailer_id'])
        product = products.get(g['product_id']) if g['product_id'] else None
        recent = CustomerReport.objects.filter(
            status=status_filter, retailer_id=g['retailer_id'], product_id=g['product_id'],
        ).order_by('-created_at')[:5]
        results.append({
            'target_type': 'product' if product else 'shop',
            'retailer_id': g['retailer_id'],
            'shop_name': shop.shop_name if shop else '',
            'shop_status': shop.verification_status if shop else '',
            'strikes_in_90_days': strikes_in_window(g['retailer_id']),
            'product_id': g['product_id'],
            'product_name': product.name if product else None,
            'product_image': product.image.url if product and product.image else None,
            'product_moderation_status': product.moderation_status if product else None,
            'reports': g['reports'],
            'reporters': g['reporters'],
            'needs_review': g['reporters'] >= (PRODUCT_FLAG_REPORTERS if g['product_id'] else SHOP_FLAG_REPORTERS),
            'latest': g['latest'],
            'recent': [
                {'reason': r.get_reason_display(), 'text': r.text, 'created_at': r.created_at}
                for r in recent
            ],
        })
    return paginator.get_paginated_response(results)


@api_view(['POST'])
@permission_classes([IsPlatformAdmin])
def admin_report_action(request):
    """Resolve open reports on a target: dismiss | hide_product | remove_product | strike."""
    try:
        retailer_id = int(request.data.get('retailer_id'))
    except (TypeError, ValueError):
        return Response({'retailer_id': ['Required.']}, status=status.HTTP_400_BAD_REQUEST)
    product_id = request.data.get('product_id')
    try:
        product_id = int(product_id) if product_id not in (None, '') else None
    except (TypeError, ValueError):
        return Response({'product_id': ['Must be a number.']}, status=status.HTTP_400_BAD_REQUEST)
    if not RetailerProfile.objects.filter(pk=retailer_id).exists():
        return Response({'error': 'Retailer profile not found'}, status=status.HTTP_404_NOT_FOUND)
    try:
        summary = handle_reports(
            retailer_id=retailer_id, product_id=product_id,
            action=(request.data.get('action') or '').strip(), actor=request.user,
            reason=request.data.get('reason') or '',
        )
    except TransitionError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(summary, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsPlatformAdmin])
def admin_product_review_list(request):
    """Products held by moderation (under review or hidden), oldest hold first."""
    from products.models import Product
    wanted = request.GET.get('status', 'pending_review')
    if wanted not in ('pending_review', 'hidden', 'removed'):
        return Response({'error': 'status must be pending_review, hidden or removed'}, status=status.HTTP_400_BAD_REQUEST)
    qs = (
        Product.objects.filter(moderation_status=wanted)
        .select_related('retailer', 'category')
        .order_by('moderated_at', 'id')
    )
    counts = Product.objects.aggregate(
        pending_review=Count('id', filter=Q(moderation_status='pending_review')),
        hidden=Count('id', filter=Q(moderation_status='hidden')),
        removed=Count('id', filter=Q(moderation_status='removed')),
    )
    paginator = PageNumberPagination()
    paginator.page_size = 50
    page = paginator.paginate_queryset(qs, request)
    results = [{
        'id': p.id,
        'name': p.name,
        'description': (p.description or '')[:300],
        'image': p.image.url if p.image else None,
        'category': p.category.name if p.category else None,
        'price': p.price,
        'retailer_id': p.retailer_id,
        'shop_name': p.retailer.shop_name,
        'moderation_status': p.moderation_status,
        'moderation_reason': p.moderation_reason,
        'moderated_at': p.moderated_at,
    } for p in page]
    data = paginator.get_paginated_response(results).data
    return Response({'counts': counts, **data})


@api_view(['POST'])
@permission_classes([IsPlatformAdmin])
def admin_product_moderate(request, product_id):
    """approve (allow this text from now on) | hide | remove, with a reason for hide/remove."""
    from products.models import Product
    from products.moderation import text_fingerprint

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
    action = (request.data.get('action') or '').strip()
    reason = (request.data.get('reason') or '').strip()
    if action not in ('approve', 'hide', 'remove'):
        return Response({'error': 'action must be approve, hide or remove'}, status=status.HTTP_400_BAD_REQUEST)
    if action in ('hide', 'remove') and not reason:
        return Response({'error': 'A reason is required. The retailer sees it.'}, status=status.HTTP_400_BAD_REQUEST)

    if action == 'approve':
        product.moderation_status = 'ok'
        product.moderation_reason = ''
        product.moderation_cleared_text = text_fingerprint(product.name.strip(), (product.description or '').strip())
    else:
        product.moderation_status = 'hidden' if action == 'hide' else 'removed'
        product.moderation_reason = reason[:255]
    product.moderated_at = timezone.now()
    product.save(update_fields=['moderation_status', 'moderation_reason', 'moderation_cleared_text', 'moderated_at'])
    logger.info("Admin %s %s product %s", request.user.pk, action, product.pk)
    return Response({
        'id': product.id,
        'moderation_status': product.moderation_status,
        'moderation_reason': product.moderation_reason,
    })
