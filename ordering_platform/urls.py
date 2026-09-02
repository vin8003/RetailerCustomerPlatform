"""
URL configuration for ordering_platform project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from retailers import partner_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('authentication.urls')),
    path('api/retailer/', include('retailers.urls')),
    path('api/customer/', include('customers.urls')),
    path('api/products/', include('products.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/cart/', include('cart.urls')),
    path('api/', include('offers.urls')),
    path('api/retailers/', include('retailers.urls')),
    path('api/returns/', include('returns.urls')),

    # OE-182 / F-0006 — versioned surfaces. Breaking changes → /api/v2/.
    # v1 remains until an explicit sunset is published in API_VERSIONING.
    path('api/v1/', partner_views.api_version_info, name='api_v1_version_info'),
    path('api/v1/partner/', include('retailers.partner_urls')),
    # JWT aliases (apps may keep unversioned /api/retailer|customer/)
    path(
        'api/v1/retailer/',
        include(('retailers.urls', 'retailers'), namespace='v1-retailer'),
    ),
    path(
        'api/v1/customer/',
        include(('customers.urls', 'customers'), namespace='v1-customer'),
    ),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
