from django.db.models import Avg

from customers.models import CustomerProfile
from orders.models import OrderFeedback, RetailerRating
from retailers.models import RetailerBlacklist


def sync_retailer_feedback_stats(retailer):
    avg_rating = OrderFeedback.objects.filter(order__retailer=retailer).aggregate(Avg('overall_rating'))['overall_rating__avg'] or 0
    total_ratings = OrderFeedback.objects.filter(order__retailer=retailer).count()
    retailer.average_rating = round(avg_rating, 2)
    retailer.total_ratings = total_ratings
    retailer.save(update_fields=['average_rating', 'total_ratings'])


def apply_retailer_rating_effects(rating):
    if rating.rating == 0:
        RetailerBlacklist.objects.get_or_create(
            retailer=rating.retailer,
            customer=rating.customer,
            defaults={'reason': f"Automated blacklist due to 0-star rating on Order #{rating.order.order_number}"},
        )
    profile, _ = CustomerProfile.objects.get_or_create(user=rating.customer)
    avg_rating = RetailerRating.objects.filter(customer=rating.customer).aggregate(Avg('rating'))['rating__avg'] or 0
    total_count = RetailerRating.objects.filter(customer=rating.customer).count()
    profile.average_rating = round(avg_rating, 2)
    profile.total_ratings = total_count
    profile.save(update_fields=['average_rating', 'total_ratings'])
