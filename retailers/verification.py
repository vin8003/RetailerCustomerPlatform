"""Retailer verification: automated shop checks and status transitions.

Design: docs/requirements/retailer-verification.md. One-time admin approval,
cheap automated checks that run inside the request, and an audit event for
every status change. Customer visibility is still decided only by
``RetailerProfile.objects.public()`` (approved + verified + active).
"""
import re

from django.db import transaction
from django.utils import timezone

from common.content_rules import check_text

from .models import RetailerProfile, RetailerVerificationDocument, VerificationEvent

PASS, FAIL, FLAG, MANUAL = 'pass', 'fail', 'flag', 'manual'

GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')
PINCODE_RE = re.compile(r'^[1-9][0-9]{5}$')
_GST_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

# Onboarding steps the retailer sees, and the checks each one needs.
STEPS = [
    ('phone', 'Phone number', ['phone']),
    ('shop', 'Your shop', ['shop_name', 'shop_photo']),
    ('address', 'Address and map pin', ['address']),
    ('proof', 'Business proof', ['proof']),
    ('owner_id', 'Owner ID', ['owner_id']),
]

# Fields whose change on an approved shop asks the admin to look again.
SENSITIVE_FIELDS = ('shop_name', 'address_line1', 'city', 'state', 'pincode', 'gst_number', 'pan_number')


def gstin_checksum_ok(gstin):
    """Validate the 15th character of a GSTIN (mod-36 checksum)."""
    gstin = (gstin or '').upper()
    if not GSTIN_RE.match(gstin):
        return False
    total = 0
    for i, ch in enumerate(gstin[:14]):
        product = _GST_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GST_CHARS[(36 - total % 36) % 36] == gstin[14]


def placeholder_shop_name(profile):
    user = profile.user
    return f"{user.first_name or user.username}'s Shop" if user else ''


def _row(key, label, result, detail=''):
    return {'key': key, 'label': label, 'result': result, 'detail': detail}


def _documents(profile):
    docs = {}
    for doc in RetailerVerificationDocument.objects.filter(retailer=profile).order_by('-uploaded_at'):
        docs.setdefault(doc.kind, doc)
    return docs


def _duplicates(profile):
    """Other shops sharing a GSTIN, PAN, UPI ID or contact phone."""
    others = RetailerProfile.objects.exclude(pk=profile.pk)
    found = []
    for field, label in (('gst_number', 'GSTIN'), ('pan_number', 'PAN'), ('upi_id', 'UPI ID'), ('contact_phone', 'phone')):
        value = (getattr(profile, field) or '').strip()
        if not value:
            continue
        lookup = {f'{field}__iexact': value}
        for other in others.filter(**lookup).only('id', 'shop_name')[:3]:
            found.append({'field': field, 'label': label, 'shop_id': other.id, 'shop_name': other.shop_name})
    return found


def run_checks(profile):
    """Compute every automated check for a shop. Cheap: a handful of queries."""
    user = profile.user
    docs = _documents(profile)
    rows = []

    # Phone
    phone_ok = bool(user and user.is_phone_verified)
    rows.append(_row('phone', 'Phone OTP verified', PASS if phone_ok else FAIL,
                     '' if phone_ok else 'Verify your phone number with the OTP.'))

    # Shop name
    name = (profile.shop_name or '').strip()
    if not name or name.lower() == placeholder_shop_name(profile).lower():
        rows.append(_row('shop_name', 'Shop name', FAIL, 'Enter your real shop name.'))
    else:
        result, reason, _ = check_text(name, min_len=3, max_len=60)
        if result == 'pass':
            rows.append(_row('shop_name', 'Shop name', PASS))
        elif result == 'restricted':
            rows.append(_row('shop_name', 'Shop name', MANUAL, reason))
        else:
            rows.append(_row('shop_name', 'Shop name', FAIL, reason))

    # Storefront photo: must exist; whether it looks real is the admin's call.
    rows.append(_row('shop_photo', 'Storefront photo', MANUAL if profile.shop_image else FAIL,
                     'Admin checks the photo.' if profile.shop_image else 'Add a photo of your shop front.'))

    # Address and pin
    missing = []
    if not (profile.address_line1 or '').strip():
        missing.append('address')
    if not (profile.city or '').strip():
        missing.append('city')
    if not (profile.state or '').strip():
        missing.append('state')
    if not PINCODE_RE.match(profile.pincode or ''):
        missing.append('valid pincode')
    if profile.latitude is None or profile.longitude is None or (
        float(profile.latitude) == 0 and float(profile.longitude) == 0
    ):
        missing.append('map pin')
    rows.append(_row('address', 'Address, pincode and map pin', FAIL if missing else PASS,
                     ('Missing: ' + ', '.join(missing) + '.') if missing else ''))

    # Business proof: any one of GSTIN, FSSAI, licence, shop-board photo.
    gst = (profile.gst_number or '').strip().upper()
    ptype = profile.proof_type or ('gst' if gst else '')
    if ptype == 'gst':
        if not gst:
            rows.append(_row('proof', 'Business proof (GSTIN)', FAIL, 'Enter your GSTIN.'))
        elif not gstin_checksum_ok(gst):
            rows.append(_row('proof', 'Business proof (GSTIN)', FAIL, 'GSTIN is not valid. Check for typos.'))
        else:
            pan = (profile.pan_number or '').strip().upper()
            if pan and gst[2:12] != pan:
                rows.append(_row('proof', 'Business proof (GSTIN)', FLAG, 'PAN does not match the PAN inside the GSTIN.'))
            else:
                rows.append(_row('proof', 'Business proof (GSTIN)', MANUAL, 'Format valid. Admin checks the name on GST.'))
    elif ptype in ('fssai', 'licence', 'board'):
        label = dict(RetailerProfile.PROOF_TYPE_CHOICES)[ptype]
        if ptype != 'board' and not (profile.proof_number or '').strip():
            rows.append(_row('proof', f'Business proof ({label})', FAIL, 'Enter the number.'))
        elif 'proof' not in docs:
            rows.append(_row('proof', f'Business proof ({label})', FAIL, 'Upload a photo of it.'))
        else:
            rows.append(_row('proof', f'Business proof ({label})', MANUAL, 'Admin checks the document.'))
    else:
        rows.append(_row('proof', 'Business proof', FAIL, 'Choose GST, FSSAI, licence or shop board photo.'))

    # Owner ID
    rows.append(_row('owner_id', 'Owner ID', MANUAL if 'owner_id' in docs else FAIL,
                     'Admin checks the ID.' if 'owner_id' in docs else 'Upload a photo of your ID.'))

    # Duplicates (never blocks; the admin decides)
    dups = _duplicates(profile)
    if dups:
        detail = '; '.join(f"Same {d['label']} as shop #{d['shop_id']} ({d['shop_name']})" for d in dups)
        rows.append(_row('duplicates', 'Duplicate GSTIN / PAN / UPI / phone', FLAG, detail))
    else:
        rows.append(_row('duplicates', 'Duplicate GSTIN / PAN / UPI / phone', PASS, 'None found.'))

    return rows


def summarize(rows):
    by_key = {r['key']: r for r in rows}
    steps = []
    for key, label, needs in STEPS:
        failing = [by_key[n] for n in needs if by_key.get(n, {}).get('result') == FAIL]
        steps.append({
            'key': key,
            'label': label,
            'done': not failing,
            'detail': ' '.join(f['detail'] for f in failing if f['detail']),
        })
    counts = {k: sum(1 for r in rows if r['result'] == k) for k in (PASS, FAIL, FLAG, MANUAL)}
    return {
        'checks': rows,
        'steps': steps,
        'counts': counts,
        'ready': counts[FAIL] == 0,
        'ran_at': timezone.now().isoformat(),
    }


def refresh_checks(profile, save=True):
    data = summarize(run_checks(profile))
    profile.verification_checks = data
    if save:
        RetailerProfile.objects.filter(pk=profile.pk).update(verification_checks=data)
    return data


# --------------------------------------------------------------------------
# Status transitions
# --------------------------------------------------------------------------

class TransitionError(ValueError):
    pass


# action -> (allowed from statuses, to status, reason required)
ADMIN_ACTIONS = {
    'approve': ({'pending', 'needs_changes', 'rejected', 'approved'}, 'approved', False),
    'request_changes': ({'pending', 'approved'}, 'needs_changes', True),
    'reject': ({'pending', 'needs_changes', 'approved', 'suspended'}, 'rejected', False),
    'suspend': ({'approved'}, 'suspended', True),
    'reinstate': ({'suspended'}, 'approved', False),
    'mark_reviewed': ({'approved'}, 'approved', False),
}
DEFAULT_REJECT_REASON = 'Verification rejected by administrator.'


def _record(profile, actor, action, from_status, to_status, reason='', details=None):
    return VerificationEvent.objects.create(
        retailer=profile, actor=actor, action=action,
        from_status=from_status or '', to_status=to_status or '',
        reason=reason or '', details=details or {},
    )


def apply_admin_action(profile_id, action, actor, reason=''):
    """Run an admin action atomically. Returns the updated profile."""
    if action not in ADMIN_ACTIONS:
        raise TransitionError(
            "Invalid action. Must be one of: " + ', '.join(sorted(ADMIN_ACTIONS)) + '.'
        )
    allowed_from, to_status, reason_required = ADMIN_ACTIONS[action]
    reason = (reason or '').strip()
    if reason_required and not reason:
        raise TransitionError('A reason is required for this action.')
    if action == 'reject' and not reason:
        reason = DEFAULT_REJECT_REASON

    with transaction.atomic():
        profile = RetailerProfile.objects.select_for_update().get(pk=profile_id)
        previous = profile.verification_status
        if previous not in allowed_from:
            raise TransitionError(f"Cannot {action.replace('_', ' ')} a shop that is {previous.replace('_', ' ')}.")

        fields = ['verification_status', 'is_verified', 'rejection_reason',
                  'verification_review_needed', 'updated_at']
        profile.verification_status = to_status
        profile.is_verified = to_status == 'approved'
        profile.verification_review_needed = False
        if to_status == 'approved':
            profile.rejection_reason = ''
            # First approval switches the shop on; a re-approval or a
            # reinstatement keeps whatever active state the retailer chose.
            if action == 'approve' and previous != 'approved':
                profile.is_active = True
                fields.append('is_active')
        else:
            profile.rejection_reason = reason
        if to_status == 'rejected':
            profile.is_active = False
            fields.append('is_active')
        profile.save(update_fields=fields)
        _record(profile, actor, action, previous, to_status, reason)
    return profile


def submit_for_review(profile, actor):
    """Retailer submits the checklist. Returns (ok, summary)."""
    data = refresh_checks(profile)
    if not data['ready']:
        return False, data
    with transaction.atomic():
        locked = RetailerProfile.objects.select_for_update().get(pk=profile.pk)
        previous = locked.verification_status
        if previous not in ('pending', 'needs_changes'):
            raise TransitionError(f'Shop is already {previous.replace("_", " ")}.')
        locked.verification_status = 'pending'
        locked.is_verified = False
        locked.verification_submitted_at = timezone.now()
        locked.verification_checks = data
        locked.save(update_fields=['verification_status', 'is_verified', 'verification_submitted_at',
                                   'verification_checks', 'updated_at'])
        _record(locked, actor, 'submit', previous, 'pending', '',
                {'counts': data['counts']})
    profile.refresh_from_db()
    return True, data


def snapshot_sensitive(profile):
    return {f: (getattr(profile, f) or '') for f in SENSITIVE_FIELDS}


def note_profile_change(profile, before, actor):
    """After a retailer edit: flag approved shops whose key details changed."""
    after = snapshot_sensitive(profile)
    changed = {f: {'from': str(before[f]), 'to': str(after[f])} for f in SENSITIVE_FIELDS if str(before[f]) != str(after[f])}
    if not changed:
        return None
    if profile.verification_status == 'approved':
        RetailerProfile.objects.filter(pk=profile.pk).update(verification_review_needed=True)
        profile.verification_review_needed = True
    return _record(profile, actor, 'profile_changed', profile.verification_status,
                   profile.verification_status, '', {'changed': changed})


def retailer_payload(profile):
    data = summarize(run_checks(profile))
    return {
        'verification_status': profile.verification_status,
        'is_verified': profile.is_verified,
        'reason': profile.rejection_reason or '',
        'submitted_at': profile.verification_submitted_at,
        'review_needed': profile.verification_review_needed,
        'proof_type': profile.proof_type,
        'proof_number': profile.proof_number,
        'documents': [
            {'id': d.id, 'kind': d.kind, 'uploaded_at': d.uploaded_at}
            for d in _documents(profile).values()
        ],
        **data,
    }
