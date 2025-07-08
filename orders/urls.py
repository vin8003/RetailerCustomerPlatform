from django.urls import path
from . import views

urlpatterns = [
    # Order management
    path('place/', views.place_order, name='place_order'),
    path('current/', views.get_current_orders, name='get_current_orders'),
    path('history/', views.get_order_history, name='get_order_history'),
    path('<int:order_id>/', views.get_order_detail, name='get_order_detail'),
    path('<int:order_id>/status/', views.update_order_status, name='update_order_status'),
    path('<int:order_id>/cancel/', views.cancel_order, name='cancel_order'),
    path('stats/', views.get_order_stats, name='get_order_stats'),
    
    # Feedback and returns
    path('<int:order_id>/feedback/', views.create_order_feedback, name='create_order_feedback'),
    path('<int:order_id>/return/', views.create_return_request, name='create_return_request'),
]
