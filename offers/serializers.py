from rest_framework import serializers
from .models import Offer, OfferTarget

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
        
        # Update targets
        if targets_data is not None and self.context['request'].method in ['PUT', 'PATCH']:
            if targets_data:
               instance.targets.all().delete()
               for target_data in targets_data:
                   OfferTarget.objects.create(offer=instance, **target_data)
                   
        return instance
