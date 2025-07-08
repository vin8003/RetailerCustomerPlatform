from django.urls import path
from . import views

urlpatterns = [
    # Retailer profile management
    path('profile/', views.get_retailer_profile, name='get_retailer_profile'),
    path('profile/create/', views.create_retailer_profile, name='create_retailer_profile'),
    path('profile/update/', views.update_retailer_profile, name='update_retailer_profile'),
    path('operating-hours/', views.update_operating_hours, name='update_operating_hours'),
    
    # Public retailer endpoints
    path('', views.list_retailers, name='list_retailers'),
    path('<int:retailer_id>/', views.get_retailer_detail, name='get_retailer_detail'),
    path('search/', views.search_retailers, name='search_retailers'),
    path('categories/', views.get_retailer_categories, name='get_retailer_categories'),
    
    # Reviews
    path('<int:retailer_id>/reviews/', views.get_retailer_reviews, name='get_retailer_reviews'),
    path('<int:retailer_id>/reviews/create/', views.create_retailer_review, name='create_retailer_review'),
]
