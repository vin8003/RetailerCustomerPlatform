from django.urls import path
from . import views

urlpatterns = [
    # Retailer product management
    path('', views.get_retailer_products, name='get_retailer_products'),
    path('create/', views.create_product, name='create_product'),
    path('<int:product_id>/', views.get_product_detail, name='get_product_detail'),
    path('<int:product_id>/update/', views.update_product, name='update_product'),
    path('<int:product_id>/delete/', views.delete_product, name='delete_product'),
    path('upload/', views.upload_products_excel, name='upload_products_excel'),
    path('stats/', views.get_product_stats, name='get_product_stats'),
    
    # Public product endpoints
    path('retailer/<int:retailer_id>/', views.get_retailer_products_public, name='get_retailer_products_public'),
    path('retailer/<int:retailer_id>/<int:product_id>/', views.get_product_detail_public, name='get_product_detail_public'),
    
    # Categories and brands
    path('categories/', views.get_product_categories, name='get_product_categories'),
    path('brands/', views.get_product_brands, name='get_product_brands'),
]
