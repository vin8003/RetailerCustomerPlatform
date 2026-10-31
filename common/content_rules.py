"""Cheap text checks shared by shop and product moderation.

Pure string checks, no network and no extra service, so they can run inside
the request on the small production VM. See
docs/requirements/retailer-verification.md (sections 3.2 and 4.3).
"""
import re

# Banned outright (decided 2026-10-31): alcohol, tobacco, adult, weapons.
BANNED_PATTERNS = {
    'alcohol': r'\b(whisky|whiskey|vodka|beer|rum|wine|brandy|liquor|daru|sharab|scotch|tequila)\b',
    'tobacco': r'\b(cigarettes?|cigars?|bidi|beedi|gutka|gutkha|tobacco|tambaku|hookah|zarda|khaini|vape)\b',
    'adult': r'\b(porn|xxx|sex\s*toys?|adult\s*toys?|escort)\b',
    'weapons': r'\b(pistol|revolver|guns?|bullets?|ammunition|ammo|dagger|katta)\b',
}
# Allowed, but an admin approves each listing first.
RESTRICTED_PATTERNS = {
    'medicine': r'\b(tablets?|capsules?|syrup|medicine|paracetamol|antibiotic|injection)\b',
    'pesticide': r'\b(pesticide|insecticide|rat\s*poison|weedicide|herbicide)\b',
}
# Light abuse list; extend as real cases show up.
ABUSE_PATTERNS = r'\b(fuck|shit|bitch|bastard|chutiya|madarchod|behenchod|bhenchod|randi|gandu)\b'

_PHONE_RE = re.compile(r'(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)')
_URL_RE = re.compile(r'https?://|www\.|\.(?:com|in|net|org)\b|wa\.me', re.I)
_SPAM_RE = re.compile(r'[!@#$%^&*~]{3,}|(.)\1{5,}')

_BANNED = {k: re.compile(v, re.I) for k, v in BANNED_PATTERNS.items()}
_RESTRICTED = {k: re.compile(v, re.I) for k, v in RESTRICTED_PATTERNS.items()}
_ABUSE = re.compile(ABUSE_PATTERNS, re.I)


def check_text(text, *, min_len=3, max_len=60):
    """Return (result, reason, category).

    result is one of: 'pass', 'fail' (fix the text), 'banned', 'restricted'.
    """
    value = (text or '').strip()
    if len(value) < min_len:
        return 'fail', f'Must be at least {min_len} characters.', None
    if max_len and len(value) > max_len:
        return 'fail', f'Must be at most {max_len} characters.', None
    for category, rx in _BANNED.items():
        if rx.search(value):
            return 'banned', f'Banned category: {category}.', category
    if _ABUSE.search(value):
        return 'fail', 'Contains offensive words.', None
    if _PHONE_RE.search(re.sub(r'[\s-]', '', value)) or _URL_RE.search(value):
        return 'fail', 'Remove phone numbers or links.', None
    if _SPAM_RE.search(value):
        return 'fail', 'Looks like spam (symbols or repeated letters).', None
    for category, rx in _RESTRICTED.items():
        if rx.search(value):
            return 'restricted', f'Restricted category: {category}. Needs admin approval.', category
    return 'pass', '', None
