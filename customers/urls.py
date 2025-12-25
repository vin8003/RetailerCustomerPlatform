from django.urls import path
from . import views

urlpatterns = [
    # Customer profile
    path('profile/', views.get_customer_profile, name='get_customer_profile'),
    path('profile/update/', views.update_customer_profile, name='update_customer_profile'),
    path('dashboard/', views.get_customer_dashboard, name='get_customer_dashboard'),
    
    # Address management
    path('addresses/', views.get_customer_addresses, name='get_customer_addresses'),
    path('addresses/create/', views.create_customer_address, name='create_customer_address'),
    path('addresses/<int:address_id>/', views.get_customer_address, name='get_customer_address'),
    path('addresses/<int:address_id>/update/', views.update_customer_address, name='update_customer_address'),
    path('addresses/<int:address_id>/delete/', views.delete_customer_address, name='delete_customer_address'),
    
    # Wishlist
    path('wishlist/', views.get_customer_wishlist, name='get_customer_wishlist'),
    path('wishlist/add/', views.add_to_wishlist, name='add_to_wishlist'),
    path('wishlist/remove/<int:product_id>/', views.remove_from_wishlist, name='remove_from_wishlist'),
    
    # Notifications
    path('notifications/', views.get_customer_notifications, name='get_customer_notifications'),
    path('notifications/<int:notification_id>/read/', views.mark_notification_read, name='mark_notification_read'),
    
    # Rewards
    path('reward-configuration/', views.get_reward_configuration, name='get_reward_configuration'),
]
