"""Customer reports, strikes and the thresholds that act on them.

Design: docs/requirements/retailer-verification.md section 5.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import CustomerReport, RetailerProfile, RetailerStrike
from .verification import TransitionError, _record, apply_admin_action

PRODUCT_HIDE_REPORTERS = 3      # distinct customers with open reports on one product
SHOP_FLAG_REPORTERS = 5         # distinct customers reporting a shop within the window
SHOP_FLAG_WINDOW = timedelta(days=7)
STRIKES_TO_SUSPEND = 3
STRIKE_WINDOW = timedelta(days=90)
REPORT_HOLD_PREFIX = 'Reports: '


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


def _apply_thresholds(report):
    now = timezone.now()
    if report.product_id:
        count = open_reporters(report.retailer_id, report.product_id)
        product = report.product
        if count >= PRODUCT_HIDE_REPORTERS and product.moderation_status == 'ok':
            product.moderation_status = 'pending_review'
            product.moderation_reason = f"{REPORT_HOLD_PREFIX}reported by {count} customers. Being reviewed."
            product.moderated_at = now
            product.save(update_fields=['moderation_status', 'moderation_reason', 'moderated_at'])
    shop_reporters = (
        CustomerReport.objects.filter(retailer_id=report.retailer_id, created_at__gte=now - SHOP_FLAG_WINDOW)
        .exclude(reporter__isnull=True).values('reporter_id').distinct().count()
    )
    if shop_reporters >= SHOP_FLAG_REPORTERS:
        updated = RetailerProfile.objects.filter(
            pk=report.retailer_id, verification_review_needed=False,
        ).update(verification_review_needed=True)
        if updated:
            profile = RetailerProfile.objects.get(pk=report.retailer_id)
            _record(profile, None, 'reports_threshold', profile.verification_status, profile.verification_status,
                    f'{shop_reporters} customers reported this shop in 7 days.')


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
    summary = {'action': action, 'suspended': False, 'strikes_in_90_days': None}
    with transaction.atomic():
        reports = CustomerReport.objects.select_for_update().filter(retailer_id=retailer_id, status='open')
        reports = reports.filter(product_id=product_id) if product_id else reports.filter(product__isnull=True)
        product = Product.objects.select_for_update().filter(pk=product_id, retailer_id=retailer_id).first() if product_id else None
        if product_id and product is None:
            raise TransitionError('Product not found for this shop.')

        if action == 'dismiss':
            if product and product.moderation_status == 'pending_review' and product.moderation_reason.startswith(REPORT_HOLD_PREFIX):
                product.moderation_status = 'ok'
                product.moderation_reason = ''
                product.moderated_at = now
                product.save(update_fields=['moderation_status', 'moderation_reason', 'moderated_at'])
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
        if strikes >= STRIKES_TO_SUSPEND and profile.verification_status == 'approved':
            apply_admin_action(retailer_id, 'suspend', actor,
                               f'{strikes} policy strikes in 90 days. Latest: {reason}')
            summary['suspended'] = True
    return summary
