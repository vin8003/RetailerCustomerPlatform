from django.urls import path
from . import views

urlpatterns = [
    # Retailer profile management
    path('profile/', views.get_retailer_profile, name='get_retailer_profile'),
    path('profile/create/', views.create_retailer_profile, name='create_retailer_profile'),
    path('profile/update/', views.update_retailer_profile, name='update_retailer_profile'),
    path('operating-hours/', views.update_operating_hours, name='update_operating_hours'),
    path('reward-config/', views.manage_reward_configuration, name='manage_reward_configuration'),

    # Organization (tenant parent) — staff-admin writes (OE-97 / F-0001)
    # Staff roles / RBAC (OE-98 / F-0002)
    # Registered before <int:retailer_id>/ so "org" is not captured as an id.
    path('org/', views.organization_me, name='organization_me'),
    path('org/<int:org_id>/', views.organization_detail, name='organization_detail'),
    path(
        'org/<int:org_id>/permissions/',
        views.organization_permission_catalog,
        name='organization_permission_catalog',
    ),
    path(
        'org/<int:org_id>/roles/',
        views.organization_roles,
        name='organization_roles',
    ),
    path(
        'org/<int:org_id>/roles/<int:role_id>/',
        views.organization_role_detail,
        name='organization_role_detail',
    ),
    path(
        'org/<int:org_id>/staff/',
        views.organization_staff,
        name='organization_staff',
    ),
    path(
        'org/<int:org_id>/staff/<int:membership_id>/',
        views.organization_staff_detail,
        name='organization_staff_detail',
    ),

    # Public retailer endpoints
    path('', views.list_retailers, name='list_retailers'),
    path('cities/', views.list_operational_cities, name='list_operational_cities'),
    path('geo-estimate/', views.geo_estimate, name='geo_estimate'),
    path('search/', views.search_retailers, name='search_retailers'),
    path('categories/', views.get_retailer_categories, name='get_retailer_categories'),
    path('<int:retailer_id>/', views.get_retailer_detail, name='get_retailer_detail'),

    # Reviews
    path('<int:retailer_id>/reviews/', views.get_retailer_reviews, name='get_retailer_reviews'),
    path('<int:retailer_id>/reviews/create/', views.create_retailer_review, name='create_retailer_review'),
]
