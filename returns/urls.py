from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SalesReturnViewSet, PurchaseReturnViewSet

router = DefaultRouter()
router.register(r'sales', SalesReturnViewSet, basename='sales-return')
router.register(r'purchase', PurchaseReturnViewSet, basename='purchase-return')

urlpatterns = [
    path('', include(router.urls)),
]
