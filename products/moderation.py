"""Automatic product text moderation, run on every Product.save().

Cheap string checks only (common/content_rules.py), so it is safe on the small
production VM. Design: docs/requirements/retailer-verification.md section 4.

- Master-catalog items whose name is the curated name are trusted.
- Banned categories (alcohol, tobacco, adult, weapons) and abuse, phone
  numbers, links or spam -> 'hidden' with a reason the retailer sees.
- Restricted categories (medicines, pesticides) -> 'pending_review'.
- Clean text clears a hold that this module set earlier ("Auto:" reasons),
  but never one set by reports or by an admin.
"""
import hashlib

from django.db.models.signals import post_init
from django.utils import timezone

from common.content_rules import check_text

AUTO_PREFIX = 'Auto: '
TEXT_FIELDS = ('name', 'description')


def text_fingerprint(name, description):
    return hashlib.sha1(f"{name or ''}\n{description or ''}".encode('utf-8')).hexdigest()[:40]


def snapshot(sender, instance, **kwargs):
    instance._moderation_snapshot = (instance.__dict__.get('name'), instance.__dict__.get('description'))


def connect(product_model):
    post_init.connect(snapshot, sender=product_model, dispatch_uid='product_moderation_snapshot')


def evaluate(product):
    """Return (status, reason) for the product's current text."""
    name = (product.name or '').strip()
    description = (product.description or '').strip()

    master = getattr(product, 'master_product', None) if product.master_product_id else None
    if master is not None and master.name.strip().lower() == name.lower() and not description:
        return 'ok', ''
    if product.moderation_cleared_text and product.moderation_cleared_text == text_fingerprint(name, description):
        return 'ok', ''

    worst = ('ok', '')
    for label, value, kwargs in (
        ('name', name, {'min_len': 1, 'max_len': 255}),
        ('description', description[:2000], {'min_len': 0, 'max_len': None}),
    ):
        if not value:
            continue
        result, reason, _category = check_text(value, **kwargs)
        if result in ('banned', 'fail'):
            return 'hidden', f"{AUTO_PREFIX}{reason} (in the {label})"
        if result == 'restricted' and worst[0] == 'ok':
            worst = ('pending_review', f"{AUTO_PREFIX}{reason}")
    return worst


MODERATION_FIELDS = ('moderation_status', 'moderation_reason', 'moderated_at')


def apply_text_moderation(product, update_fields=None):
    """Called from Product.save() before writing. Returns save() update_fields to use."""
    if update_fields is not None and not set(update_fields) & set(TEXT_FIELDS):
        return update_fields
    if product.moderation_status == 'removed':
        return update_fields
    before = getattr(product, '_moderation_snapshot', (None, None))
    is_new = product._state.adding
    changed = is_new or before != (product.name, product.description)
    if not changed:
        return update_fields

    status, reason = evaluate(product)
    current = product.moderation_status
    auto_hold = current in ('hidden', 'pending_review') and (product.moderation_reason or '').startswith(AUTO_PREFIX)

    if status != 'ok':
        if current == 'ok' or auto_hold:
            product.moderation_status = status
            product.moderation_reason = reason[:255]
            product.moderated_at = timezone.now()
    elif auto_hold:
        product.moderation_status = 'ok'
        product.moderation_reason = ''
        product.moderated_at = timezone.now()

    product._moderation_snapshot = (product.name, product.description)
    if update_fields is not None:
        # Write the moderation columns in the same UPDATE.
        return list(dict.fromkeys([*update_fields, *MODERATION_FIELDS]))
    return update_fields
