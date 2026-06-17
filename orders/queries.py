from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from retailers.models import RetailerProfile

from .models import Order, OrderFeedback, RetailerRating


STATUS_ALIASES = {
    'shipped': 'out_for_delivery',
}


def annotate_order_list_fields(qs):
    has_feedback_subquery = Exists(OrderFeedback.objects.filter(order=OuterRef('pk')))
    has_rating_subquery = Exists(RetailerRating.objects.filter(order=OuterRef('pk')))
    return qs.select_related('retailer', 'customer').annotate(
        items_count_annotated=Count('items'),
        has_feedback_annotated=has_feedback_subquery,
        has_rating_annotated=has_rating_subquery,
    )


def base_order_queryset_for_user(user):
    qs = annotate_order_list_fields(Order.objects.all())

    if user.user_type == 'customer':
        return qs.filter(customer=user).order_by('-created_at')

    if user.user_type == 'retailer':
        retailer = RetailerProfile.objects.get(user=user)
        return qs.filter(retailer=retailer).order_by('-created_at')

    raise ValueError('Invalid user type')


def apply_order_filters(qs, params):
    status_filter = params.get('status')
    if status_filter:
        status_filter = STATUS_ALIASES.get(status_filter, status_filter)
        qs = qs.filter(status=status_filter)

    start_date = params.get('start_date')
    if start_date:
        try:
            parsed_start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
            qs = qs.filter(created_at__date__gte=parsed_start_date)
        except ValueError:
            pass

    end_date = params.get('end_date')
    if end_date:
        try:
            parsed_end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
            qs = qs.filter(created_at__date__lte=parsed_end_date)
        except ValueError:
            pass

    search = params.get('search')
    if search:
        qs = qs.filter(order_number__icontains=search)

    return qs
