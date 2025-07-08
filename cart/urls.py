from django.urls import path
from . import views

urlpatterns = [
    # Cart management
    path('', views.get_cart, name='get_cart'),
    path('add/', views.add_to_cart, name='add_to_cart'),
    path('items/<int:item_id>/', views.update_cart_item, name='update_cart_item'),
    path('items/<int:item_id>/remove/', views.remove_cart_item, name='remove_cart_item'),
    path('clear/', views.clear_cart, name='clear_cart'),
    
    # Cart utilities
    path('summary/', views.get_cart_summary, name='get_cart_summary'),
    path('validate/', views.validate_cart, name='validate_cart'),
    path('count/', views.get_cart_count, name='get_cart_count'),
]
