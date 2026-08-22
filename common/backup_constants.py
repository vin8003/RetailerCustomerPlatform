import base64

# Gmail attachment limit used by `manage.py backup_database` (checked after base64 encoding).
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def encoded_attachment_size(content: bytes) -> int:
    return len(base64.b64encode(content))


def attachment_exceeds_email_limit(content: bytes) -> bool:
    return encoded_attachment_size(content) > MAX_ATTACHMENT_BYTES
