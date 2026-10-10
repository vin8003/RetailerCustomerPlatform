"""Partner v1 URL routes (OE-182 / F-0006)."""
from django.urls import path

from . import partner_views

urlpatterns = [
    path('scopes/', partner_views.partner_scope_catalog, name='partner_v1_scopes'),
    path('org/', partner_views.partner_organization, name='partner_v1_org'),
    path('locations/', partner_views.partner_locations, name='partner_v1_locations'),
    path(
        'locations/<int:location_id>/',
        partner_views.partner_location_detail,
        name='partner_v1_location_detail',
    ),
]
