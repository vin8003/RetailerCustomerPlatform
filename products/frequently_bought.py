"""Frequently bought together (KAN-17).

Recommend add-ons from the current cart using product group, category,
and simple co-purchase counts. No ML models.
"""
import logging

from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from common.error_utils import format_exception
from retailers.models import RetailerProfile

logger = logging.getLogger(__name__)

FBT_LIMIT = 10


def _parse_product_ids(raw):
    ids = []
    if not raw:
        return ids
    for part in str(raw).split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def _cart_product_ids(user, retailer):
    if not getattr(user, 'is_authenticated', False):
        return []
    if getattr(user, 'user_type', None) != 'customer':
        return []
    from cart.models import CartItem
    return list(
        CartItem.objects.filter(
            cart__customer=user,
            cart__retailer=retailer,
        ).values_list('product_id', flat=True)
    )


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_frequently_bought_together(request, retailer_id):
    """Return high-affinity add-ons for the current cart or seed product ids."""
    try:
        retailer = get_object_or_404(RetailerProfile, id=retailer_id, is_active=True)
        seed_ids = set(_parse_product_ids(request.query_params.get('product_ids')))
        seed_ids.update(_cart_product_ids(request.user, retailer))
        if not seed_ids:
            return Response([], status=status.HTTP_200_OK)

        from products.models import Product
        from products.serializers import ProductListSerializer
        from orders.models import OrderItem
        from offers.models import Offer

        seeds = list(Product.objects.filter(
            id__in=seed_ids,
            retailer=retailer,
        ).only('id', 'category_id', 'product_group'))
        if not seeds:
            return Response([], status=status.HTTP_200_OK)

        category_ids = {p.category_id for p in seeds if p.category_id}
        groups = {p.product_group for p in seeds if p.product_group}

        catalog = Product.objects.filter(
            retailer=retailer,
            is_active=True,
            is_available=True,
        ).exclude(id__in=seed_ids)
        catalog = catalog.filter(Q(track_inventory=False) | Q(quantity__gt=0))

        affinity = Q()
        if category_ids:
            affinity |= Q(category_id__in=category_ids)
        if groups:
            affinity |= Q(product_group__in=groups)
        related = catalog.filter(affinity) if affinity else catalog.none()

        co_purchased_ids = list(
            OrderItem.objects.filter(
                order__retailer=retailer,
                order__items__product_id__in=seed_ids,
            ).exclude(
                product_id__in=seed_ids
            ).values('product_id').annotate(
                freq=Count('id')
            ).order_by('-freq').values_list('product_id', flat=True)[:FBT_LIMIT]
        )

        ranked_ids = []
        for pid in co_purchased_ids:
            if pid not in ranked_ids:
                ranked_ids.append(pid)
        for pid in related.values_list('id', flat=True)[:FBT_LIMIT * 2]:
            if pid not in ranked_ids:
                ranked_ids.append(pid)

        if not ranked_ids:
            return Response([], status=status.HTTP_200_OK)

        products = catalog.filter(id__in=ranked_ids[:FBT_LIMIT]).select_related(
            'master_product', 'category', 'brand', 'retailer'
        ).annotate(
            average_rating_annotated=Avg('reviews__rating'),
            review_count_annotated=Count('reviews')
        )
        by_id = {p.id: p for p in products}
        ordered = [by_id[pid] for pid in ranked_ids if pid in by_id][:FBT_LIMIT]

        active_offers = list(Offer.objects.filter(
            retailer=retailer,
            is_active=True,
            start_date__lte=timezone.now()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now())
        ).order_by('-priority').prefetch_related('targets'))

        serializer = ProductListSerializer(
            ordered,
            many=True,
            context={'request': request, 'active_offers': active_offers},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting frequently bought together: {str(e)}")
        return Response(
            {'error': format_exception(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
