from rest_framework import viewsets, permissions, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Offer, OfferTarget
from products.models import Product

class OfferTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfferTarget
        fields = ['id', 'target_type', 'product', 'category', 'brand', 'is_excluded']

class OfferSerializer(serializers.ModelSerializer):
    targets = OfferTargetSerializer(many=True, required=False)
    
    class Meta:
        model = Offer
        fields = '__all__'
        read_only_fields = ['retailer', 'current_redemptions', 'created_at']

    def create(self, validated_data):
        targets_data = validated_data.pop('targets', [])
        # Assign retailer from context
        user = self.context['request'].user
        retailer = user.retailer_profile
        validated_data['retailer'] = retailer
        
        offer = Offer.objects.create(**validated_data)
        
        for target_data in targets_data:
            OfferTarget.objects.create(offer=offer, **target_data)
            
        return offer

    def update(self, instance, validated_data):
        targets_data = validated_data.pop('targets', [])
        
        # Update fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update targets (Full replace approach for simplicity or handle diffs)
        if targets_data is not None and self.context['request'].method in ['PUT', 'PATCH']:
            # Simplest: Delete all and recreate if provided
            # Note: In PATCH, if 'targets' key is missing, we don't touch them.
            # If empty list, we clear them (if passed).
            # But DRF partial update logic for nested writable serializers is tricky.
            # Let's assume frontend sends full list on edit for now.
            if targets_data: # If list is provided
               instance.targets.all().delete()
               for target_data in targets_data:
                   OfferTarget.objects.create(offer=instance, **target_data)
                   
        return instance

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
