"""Customer reports, strikes and the thresholds that act on them.

Design: docs/requirements/retailer-verification.md section 5.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import CustomerReport, RetailerProfile, RetailerStrike
from .verification import TransitionError, _record

# Reports and strikes never hide anything on their own: crossing a threshold only
# puts the target in front of an admin, so the report button cannot be used to
# take a competitor's shop or product down.
PRODUCT_FLAG_REPORTERS = 3      # distinct customers with open reports on one product
SHOP_FLAG_REPORTERS = 5         # distinct customers reporting a shop within the window
SHOP_FLAG_WINDOW = timedelta(days=7)
STRIKES_TO_FLAG = 3             # strikes in the window that put the shop up for a suspend decision
STRIKE_WINDOW = timedelta(days=90)


def open_reporters(retailer_id, product_id=None):
    qs = CustomerReport.objects.filter(retailer_id=retailer_id, status='open')
    qs = qs.filter(product_id=product_id) if product_id else qs.filter(product__isnull=True)
    return qs.exclude(reporter__isnull=True).values('reporter_id').distinct().count()


def file_report(*, retailer, product, reporter, reason, text=''):
    """Create a report (one open report per reporter and target). Returns (report, created)."""
    existing = CustomerReport.objects.filter(
        retailer=retailer, product=product, reporter=reporter, status='open',
    ).first()
    if existing:
        return existing, False
    report = CustomerReport.objects.create(
        retailer=retailer, product=product, reporter=reporter, reason=reason, text=(text or '')[:1000],
    )
    _apply_thresholds(report)
    return report, True


def _flag_shop(retailer_id, action, reason, actor=None, details=None):
    """Mark the shop for admin review once (no visibility change) and log why."""
    updated = RetailerProfile.objects.filter(
        pk=retailer_id, verification_review_needed=False,
    ).update(verification_review_needed=True)
    if updated:
        profile = RetailerProfile.objects.get(pk=retailer_id)
        _record(profile, actor, action, profile.verification_status, profile.verification_status, reason, details)
    return bool(updated)


def _apply_thresholds(report):
    now = timezone.now()
    if report.product_id and open_reporters(report.retailer_id, report.product_id) == PRODUCT_FLAG_REPORTERS:
        # Log once when the product crosses the line; the product stays live.
        profile = RetailerProfile.objects.get(pk=report.retailer_id)
        _record(profile, None, 'product_reports_threshold', profile.verification_status,
                profile.verification_status,
                f'{PRODUCT_FLAG_REPORTERS} customers reported "{report.product.name}". Needs review.',
                {'product_id': report.product_id})
    shop_reporters = (
        CustomerReport.objects.filter(retailer_id=report.retailer_id, created_at__gte=now - SHOP_FLAG_WINDOW)
        .exclude(reporter__isnull=True).values('reporter_id').distinct().count()
    )
    if shop_reporters >= SHOP_FLAG_REPORTERS:
        _flag_shop(report.retailer_id, 'reports_threshold', f'{shop_reporters} customers reported this shop in 7 days.')


def strikes_in_window(retailer_id):
    return RetailerStrike.objects.filter(
        retailer_id=retailer_id, created_at__gte=timezone.now() - STRIKE_WINDOW,
    ).count()


ADMIN_REPORT_ACTIONS = ('dismiss', 'hide_product', 'remove_product', 'strike')


def handle_reports(*, retailer_id, product_id, action, actor, reason=''):
    """Resolve every open report on one target. Returns a summary dict."""
    if action not in ADMIN_REPORT_ACTIONS:
        raise TransitionError('Invalid action. Must be one of: ' + ', '.join(ADMIN_REPORT_ACTIONS) + '.')
    reason = (reason or '').strip()
    if action == 'strike' and not reason:
        raise TransitionError('A reason is required for a strike.')
    if action in ('hide_product', 'remove_product') and not product_id:
        raise TransitionError('This action needs a product.')

    from products.models import Product

    now = timezone.now()
    summary = {'action': action, 'flagged_for_review': False, 'strikes_in_90_days': None}
    with transaction.atomic():
        reports = CustomerReport.objects.select_for_update().filter(retailer_id=retailer_id, status='open')
        reports = reports.filter(product_id=product_id) if product_id else reports.filter(product__isnull=True)
        product = Product.objects.select_for_update().filter(pk=product_id, retailer_id=retailer_id).first() if product_id else None
        if product_id and product is None:
            raise TransitionError('Product not found for this shop.')

        if action == 'dismiss':
            new_status = 'dismissed'
        else:
            if product and action in ('hide_product', 'remove_product', 'strike'):
                product.moderation_status = 'hidden' if action == 'hide_product' else 'removed'
                product.moderation_reason = (reason or 'Removed after customer reports.')[:255]
                product.moderated_at = now
                product.save(update_fields=['moderation_status', 'moderation_reason', 'moderated_at'])
            new_status = 'actioned'
            if action == 'strike':
                RetailerStrike.objects.create(retailer_id=retailer_id, reason=reason[:255], product=product, created_by=actor)

        count = reports.update(status=new_status, resolution=action, handled_by=actor, handled_at=now)
        summary['reports_closed'] = count

    if action == 'strike':
        strikes = strikes_in_window(retailer_id)
        summary['strikes_in_90_days'] = strikes
        profile = RetailerProfile.objects.get(pk=retailer_id)
        _record(profile, actor, 'strike', profile.verification_status, profile.verification_status, reason,
                {'product_id': product_id, 'strikes_in_90_days': strikes})
        if strikes >= STRIKES_TO_FLAG and profile.verification_status == 'approved':
            # No automatic suspension: the admin decides from the review queue.
            summary['flagged_for_review'] = _flag_shop(
                retailer_id, 'strikes_threshold',
                f'{strikes} policy strikes in 90 days. Decide whether to suspend. Latest: {reason}',
                actor, {'strikes_in_90_days': strikes},
            ) or profile.verification_review_needed
    return summary
