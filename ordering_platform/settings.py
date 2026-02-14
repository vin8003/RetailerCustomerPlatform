"""
Django settings for ordering_platform project.
"""

import os
from pathlib import Path
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
from dotenv import load_dotenv
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
if '*' in ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise.runserver_nostatic',
    'django.contrib.postgres',

    # Third party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'storages',

    # Local apps
    'authentication',
    'retailers',
    'customers',
    'products',
    'orders',
    'cart',
    'offers',
    'common',
    'fcm_django',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ordering_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ordering_platform.wsgi.application'

# Database
# https://docs.djangoproject.com/en/stable/ref/settings/#databases
import dj_database_url

# use sqlite
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'buyez_db',
        'USER': 'buyez_user',
        'PASSWORD': 'strongpassword',
        'HOST': 'localhost',
        'PORT': '5432',
        'CONN_MAX_AGE': 600,
    }
}


# Custom user model
AUTH_USER_MODEL = 'authentication.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Whitenoise storage for compressed and hashed files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'common.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'login': '5/minute',
        'otp': '3/minute',
    }
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'SIGNING_KEY': SECRET_KEY,
    'ALGORITHM': 'HS256',
    'VERIFY_SIGNATURE': True,
    'REQUIRE_EXPIRATION_TIME': True,
    'REQUIRE_ISSUED_AT': True,
}

# CORS settings
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^https?://localhost:\d+$",
        r"^https?://127.0.0.1:\d+$",
    ]
else:
    CORS_ALLOWED_ORIGIN_REGEXES = []

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
from corsheaders.defaults import default_headers

CORS_ALLOWED_ORIGINS = [
    "https://customer.ordereasy.win",
    "https://retailer.ordereasy.win",
]

CORS_ALLOWED_ORIGINS += [
    "http://localhost:3000",
    "http://localhost:5173",
]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "authorization",
    "content-type",
]

# SMS Configuration (Authkey.io)
AUTHKEY_API_KEY = os.getenv('AUTHKEY_API_KEY', '')
AUTHKEY_URL = os.getenv('AUTHKEY_URL', 'https://api.authkey.io/request')
AUTHKEY_SENDER = os.getenv('AUTHKEY_SENDER', 'SENDERID')
AUTHKEY_PE_ID = os.getenv('AUTHKEY_PE_ID', '')
AUTHKEY_TEMPLATE_ID = os.getenv('AUTHKEY_TEMPLATE_ID', '')

# OTP Settings
OTP_EXPIRY_TIME = 300  # 5 minutes in seconds
OTP_LENGTH = 6
OTP_MAX_ATTEMPTS = 3

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}

# Cache configuration
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
        'TIMEOUT': 300,
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
        }
    }
}

# Email configuration (for notifications)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)

# FCM Django Settings
FCM_DJANGO_SETTINGS = {
    "APP_VERBOSE_NAME": "Firebase Cloud Messaging",
    "FCM_SERVER_KEY": os.getenv('FCM_SERVER_KEY', ''),
    "ONE_DEVICE_PER_USER": False,
    "DELETE_INACTIVE_DEVICES": True,
}

# Firebase Admin SDK Initialization
import firebase_admin
from firebase_admin import credentials

if not firebase_admin._apps:
    try:
        # Check for service account JSON
        cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        print(f"DEBUG: Ensure CWD is {os.getcwd()}")
        print(f"DEBUG: GOOGLE_APPLICATION_CREDENTIALS = {cred_path}")
        
        if cred_path and os.path.exists(cred_path):
            print(f"DEBUG: Found valid credential file at {cred_path}")
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            print(f"DEBUG: Credential file NOT found or var not set. Using default options.")
            # Default initialization (uses GOOGLE_APPLICATION_CREDENTIALS if set,
            # but won't crash if it's not and we are just testing)
            firebase_admin.initialize_app(options={'projectId': 'buyeasy-4003f'})
    except Exception as e:
        print(f"Warning: Firebase Admin SDK could not be initialized: {e}")


CSRF_TRUSTED_ORIGINS = [
    "https://customer.ordereasy.win",
    "https://retailer.ordereasy.win",
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CONN_MAX_AGE = 600

# oracle bucket configuration
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')

# oracle bucket config
AWS_STORAGE_BUCKET_NAME = 'product_images' # The bucket you created
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400', # Tell Cloudflare to cache images for 1 day
}

# oracle bucket endpoint
AWS_S3_ENDPOINT_URL = 'https://bmvhzw5ybhpw.compat.objectstorage.ap-mumbai-1.oraclecloud.com'

# 4. The Cloudflare "Vanity" Domain
# This constructs the public URL exactly how we discussed:
# https://images.yourdomain.com/n/<namespace>/b/<bucket>/o/<filename>
# AWS_S3_CUSTOM_DOMAIN = f'images.ordereasy.win/n/bmvhzw5ybhpw/b/product_images/o'

# tell django to use s3 for media
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# ensure urls are https
AWS_S3_URL_PROTOCOL = 'https:'
AWS_QUERYSTRING_AUTH = False # Don't add messy signature tokens to the URL (since bucket is public)

# botocore config to fix oracle compatibility issues (missingcontentlength)
from botocore.config import Config
AWS_S3_REGION_NAME = 'ap-mumbai-1'
AWS_S3_CLIENT_CONFIG = Config(
    signature_version='s3v4',
    request_checksum_calculation='when_required',
    response_checksum_validation='when_required',
    s3={'addressing_style': 'path'}
)
