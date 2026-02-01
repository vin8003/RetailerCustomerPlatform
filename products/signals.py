from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from .models import ProductCategory

@receiver(post_save, sender=ProductCategory)
@receiver(post_delete, sender=ProductCategory)
def invalidate_category_tree_cache(sender, instance, **kwargs):
    """
    Invalidate the category tree cache whenever a category is created, updated, or deleted.
    """
    cache_key = 'category_tree_structure'
    cache.delete(cache_key)
    # Also invalidate any derived caches if we add them later
