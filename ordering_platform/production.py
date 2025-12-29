from .settings import *
import os

# Override base settings for production

DEBUG = False

# Security Settings
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Allowed Hosts
allowed_hosts_env = os.getenv('ALLOWED_HOSTS')
if allowed_hosts_env:
    ALLOWED_HOSTS = allowed_hosts_env.split(',')

# CORS Settings
cors_origins_env = os.getenv('CORS_ALLOWED_ORIGINS')
if cors_origins_env:
    CORS_ALLOWED_ORIGINS = cors_origins_env.split(',')
    CORS_ALLOWED_ORIGIN_REGEXES = [] # Disable regexes in production for stricter control unless needed
else:
    CORS_ALLOWED_ORIGINS = []

# CSRF Trusted Origins
# Often required if hosted behind a proxy or load balancer (like Render/Cloudflare)
csrf_trusted_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS')
if csrf_trusted_origins_env:
    CSRF_TRUSTED_ORIGINS = csrf_trusted_origins_env.split(',')
elif cors_origins_env:
    # Default to trusting CORS origins if explicit CSRF var is missing
    CSRF_TRUSTED_ORIGINS = cors_origins_env.split(',')

# Add Render.com specific handling if applicable, or generic external URL
render_external_url = os.getenv('RENDER_EXTERNAL_URL')
if render_external_url:
    if render_external_url not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(render_external_url)
    if render_external_url not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_external_url)
