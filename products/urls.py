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
    path('master/search/', views.search_master_product, name='search_master_product'), # NEW
    path('upload/check/', views.check_bulk_upload, name='check_bulk_upload'),
    path('upload/complete/', views.complete_bulk_upload, name='complete_bulk_upload'),
    
    # Visual Bulk Upload (Session Based)
    path('upload/session/create/', views.CreateUploadSessionView.as_view(), name='create_upload_session'),
    path('upload/session/active/', views.GetActiveSessionsView.as_view(), name='get_active_sessions'),
    path('upload/session/add-item/', views.AddSessionItemView.as_view(), name='add_session_item'),
    path('upload/session/<int:session_id>/', views.GetSessionDetailsView.as_view(), name='get_session_details_old'),
    path('upload/session/details/<int:session_id>/', views.GetSessionDetailsView.as_view(), name='get_session_details'),
    path('upload/session/update-items/', views.UpdateSessionItemsView.as_view(), name='update_session_items'),
    path('upload/session/commit/', views.CommitUploadSessionView.as_view(), name='commit_upload_session'),

    # Public product endpoints
    path('retailer/<int:retailer_id>/', views.get_retailer_products_public, name='get_retailer_products_public'),
    path('retailer/<int:retailer_id>/categories/', views.get_retailer_categories, name='get_retailer_categories'),
    path('retailer/<int:retailer_id>/featured/', views.get_retailer_featured_products, name='get_retailer_featured_products'),
    path('retailer/<int:retailer_id>/best-selling/', views.get_best_selling_products, name='get_best_selling_products'),
    path('retailer/<int:retailer_id>/buy-again/', views.get_buy_again_products, name='get_buy_again_products'),
    path('retailer/<int:retailer_id>/recommended/', views.get_recommended_products, name='get_recommended_products'),
    path('retailer/<int:retailer_id>/<int:product_id>/', views.get_product_detail_public, name='get_product_detail_public'),

    # Categories and brands
    path('categories/', views.get_product_categories, name='get_product_categories'),
    path('categories/create/', views.create_product_category, name='create_product_category'), # NEW

    path('brands/', views.get_product_brands, name='get_product_brands'),
    path('brands/create/', views.create_product_brand, name='create_product_brand'), # NEW

]
