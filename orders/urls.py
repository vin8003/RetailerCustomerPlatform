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
    path('<int:order_id>/modify/', views.modify_order, name='modify_order'),
    path('<int:order_id>/confirm_modification/', views.confirm_modification, name='confirm_modification'),
    path('<int:order_id>/estimated-time/', views.update_estimated_time, name='update_estimated_time'),
    path('stats/', views.get_order_stats, name='get_order_stats'),
    path('retailer-reviews/', views.get_retailer_reviews, name='get_retailer_reviews'),
    
    # Feedback and returns
    path('<int:order_id>/feedback/', views.create_order_feedback, name='create_order_feedback'),
    path('<int:order_id>/rate-customer/', views.create_retailer_rating, name='create_retailer_rating'),
    path('<int:order_id>/return/', views.create_return_request, name='create_return_request'),

    # Chat
    path('<int:order_id>/chat/', views.get_order_chat, name='get_order_chat'),
    path('<int:order_id>/chat/send/', views.send_order_message, name='send_order_message'),
    path('<int:order_id>/chat/read/', views.mark_chat_read, name='mark_chat_read'),
]
