"""Storage for private verification documents (owner ID, business proof).

The default media storage is a public bucket, so these files must never go
there. If PRIVATE_DOCS_BUCKET is set, a private S3 bucket with signed access
is used; otherwise files go to PRIVATE_MEDIA_ROOT on the server's disk, which
is outside the web root. Admins read them only through an authenticated view.
"""
import os
from functools import lru_cache

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateFileSystemStorage(FileSystemStorage):
    """Local disk outside the web root; location read from settings each time."""

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None


@lru_cache(maxsize=1)
def private_document_storage():
    bucket = getattr(settings, 'PRIVATE_DOCS_BUCKET', '')
    if bucket:
        from storages.backends.s3 import S3Storage
        return S3Storage(
            bucket_name=bucket,
            default_acl='private',
            querystring_auth=True,
            custom_domain=None,
            object_parameters={},
        )
    return PrivateFileSystemStorage()
