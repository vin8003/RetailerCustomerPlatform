from decimal import Decimal
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Offer, OfferTarget
from products.models import Product
from .serializers import OfferSerializer, OfferTargetSerializer
from django.utils import timezone
from django.db import models

class OfferViewSet(viewsets.ModelViewSet):
    serializer_class = OfferSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'retailer_profile'):
            return Offer.objects.filter(retailer=user.retailer_profile)
        return Offer.objects.none()
        
    @action(detail=False, methods=['post'], url_path='calculate')
    def calculate_cart(self, request):
        """
        Preview API for calculating offers on a dummy cart
        Payload: { items: [ {product_id: 1, quantity: 2, price: 20} ] }
        """
        from .engine import OfferEngine
        from products.models import Product
        
        class DummyItem:
            def __init__(self, pid, qty, price):
                self.id = pid
                self.quantity = qty
                self.price = Decimal(str(price))
                self.unit_price = self.price
                try: 
                    self.product = Product.objects.get(id=pid)
                except:
                    # Mock product if not found (or should we error?)
                    # For preview, maybe we trust the ID or fail.
                    # Let's try to get it, or minimal mock
                    self.product = type('obj', (object,), {'price': self.price, 'id': pid, 'category_id': None, 'brand_id': None})
        
        items_data = request.data.get('items', [])
        cart_items = []
        for i in items_data:
            cart_items.append(DummyItem(i.get('product_id'), i.get('quantity'), i.get('price')))
            
        retailer_id = request.data.get('retailer_id')
        if not retailer_id:
             # Default to current user's retailer if creating from own dashboard
             # But if Customer calls this? Customer won't call this ViewSet (Restricted to Retailer/Owner).
             # Customer uses Cart View. This is for Retailer "Test/Preview".
             if hasattr(request.user, 'retailer_profile'):
                 retailer = request.user.retailer_profile
             else:
                 return Response({"error": "Retailer ID required"}, status=400)
        else:
            from retailers.models import RetailerProfile
            retailer = RetailerProfile.objects.get(id=retailer_id)
            
        engine = OfferEngine()
        result = engine.calculate_offers(cart_items, retailer)
        return Response(result)

class PublicOfferViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OfferSerializer
    permission_classes = [permissions.AllowAny] # Or IsAuthenticated if customer login required
    
    def get_queryset(self):
        retailer_id = self.kwargs.get('retailer_id')
        if retailer_id:
            return Offer.objects.filter(
                retailer_id=retailer_id, 
                is_active=True,
                start_date__lte=timezone.now()
            ).filter(
                models.Q(end_date__isnull=True) | models.Q(end_date__gte=timezone.now())
            )
        return Offer.objects.none()
