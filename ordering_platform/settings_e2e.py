"""Settings for the Playwright e2e suite only (local runs and .github/workflows/e2e.yml).

Use with DJANGO_SETTINGS_MODULE=ordering_platform.settings_e2e. Production keeps using
ordering_platform.settings unchanged.
"""
import os

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR, MEDIA_ROOT

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

TIME_ZONE = 'Asia/Kolkata'

# Console only: the default SolarWinds syslog handler hangs startup without egress.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}

# Local file storage, never the Oracle S3 bucket.
E2E_API_ORIGIN = os.getenv('E2E_API_ORIGIN', 'http://127.0.0.1:8100')
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
        'OPTIONS': {'location': str(MEDIA_ROOT), 'base_url': f'{E2E_API_ORIGIN}/media/'},
    },
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# No real SMS / email from e2e.
AUTHKEY_API_KEY = ''
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Repeated logins across journeys would trip the production rate limits.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_RATES': {
        scope: '10000/minute' for scope in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']  # noqa: F405
    },
}
