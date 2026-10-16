from decimal import Decimal
from rest_framework import viewsets, permissions
from rest_framework.decorators import action, api_view, permission_classes
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
            
        user_type = getattr(request.user, 'user_type', 'customer')
        default_channel = 'pos' if user_type == 'retailer' else 'mobile'
        channel = request.data.get('channel', default_channel)
        engine = OfferEngine()
        result = engine.calculate_offers(cart_items, retailer, context={'channel': channel})
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


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_available_coupons(request, retailer_id):
    """
    Get all active, public coupons for a retailer that are eligible for the customer
    """
    now = timezone.now()
    qs = Offer.objects.filter(
        retailer_id=retailer_id,
        is_active=True,
        is_public=True,
        coupon_code__isnull=False,
        start_date__lte=now
    ).exclude(
        coupon_code=''
    ).filter(
        models.Q(end_date__isnull=True) | models.Q(end_date__gte=now)
    )
    
    coupons_list = []
    user = request.user if request.user.is_authenticated else None
    
    for offer in qs:
        # Check total usage limit
        if offer.usage_limit_total and offer.current_redemptions >= offer.usage_limit_total:
            continue
            
        if user:
            # Check user redemption limit
            if offer.usage_limit_per_user:
                from .models import OfferRedemption
                used = OfferRedemption.objects.filter(offer=offer, customer=user).count()
                if used >= offer.usage_limit_per_user:
                    continue
                    
            # Check target audience
            if offer.target_audience == 'first_time':
                from orders.models import Order
                has_orders = Order.objects.filter(
                    customer=user, 
                    retailer_id=retailer_id
                ).exclude(status__in=['cancelled', 'returned']).exists()
                if has_orders:
                    continue
            elif offer.target_audience == 'selected':
                if not offer.eligible_customers.filter(id=user.id).exists():
                    continue
        else:
            if offer.target_audience == 'selected':
                continue
                
        coupons_list.append({
            'id': offer.id,
            'code': offer.coupon_code,
            'name': offer.name,
            'description': offer.description,
            'benefit_type': offer.benefit_type,
            'offer_type': offer.offer_type,
            'value': float(offer.value),
            'value_type': offer.value_type,
            'min_order_value': float(offer.min_order_value),
            'max_discount_amount': float(offer.max_discount_amount) if offer.max_discount_amount else None,
            'end_date': offer.end_date,
            'target_audience': offer.target_audience
        })
        
    return Response(coupons_list)

