from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.routers import DefaultRouter
from .views import OfferViewSet, PublicOfferViewSet

router = DefaultRouter()
router.register(r'offers', OfferViewSet, basename='offer')

urlpatterns = [
    path('', include(router.urls)),
    path('offers/public/retailer/<int:retailer_id>/', PublicOfferViewSet.as_view({'get': 'list'}), name='public-retailer-offers'),
]
