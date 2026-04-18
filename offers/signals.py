from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Offer, OfferTarget


def _active_offers_cache_key(retailer_id):
    return f"active_offers:{retailer_id}"


def _clear_active_offers_cache(retailer_id):
    if retailer_id:
        cache.delete(_active_offers_cache_key(retailer_id))


@receiver(post_save, sender=Offer)
@receiver(post_delete, sender=Offer)
def clear_offer_cache_on_offer_change(sender, instance, **kwargs):
    _clear_active_offers_cache(instance.retailer_id)


@receiver(post_save, sender=OfferTarget)
@receiver(post_delete, sender=OfferTarget)
def clear_offer_cache_on_target_change(sender, instance, **kwargs):
    _clear_active_offers_cache(instance.offer.retailer_id)
