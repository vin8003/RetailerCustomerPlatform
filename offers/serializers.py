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
        eligible_customers = validated_data.pop('eligible_customers', [])
        # Assign retailer from context
        user = self.context['request'].user
        retailer = user.retailer_profile
        validated_data['retailer'] = retailer
        
        if validated_data.get('coupon_code'):
            validated_data['coupon_code'] = validated_data['coupon_code'].strip().upper()
            
        offer = Offer.objects.create(**validated_data)
        if eligible_customers:
            offer.eligible_customers.set(eligible_customers)
            
        # The engine applies an offer only to items its targets match, so an
        # offer saved without targets would silently discount nothing.
        if not targets_data:
            targets_data = [{'target_type': 'all_products'}]

        for target_data in targets_data:
            OfferTarget.objects.create(offer=offer, **target_data)
            
        return offer

    def update(self, instance, validated_data):
        targets_data = validated_data.pop('targets', [])
        eligible_customers = validated_data.pop('eligible_customers', None)
        
        if 'coupon_code' in validated_data and validated_data['coupon_code']:
            validated_data['coupon_code'] = validated_data['coupon_code'].strip().upper()
            
        # Update fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if eligible_customers is not None:
            instance.eligible_customers.set(eligible_customers)
            
        # Update targets
        if targets_data is not None and self.context['request'].method in ['PUT', 'PATCH']:
            if targets_data:
               instance.targets.all().delete()
               for target_data in targets_data:
                   OfferTarget.objects.create(offer=instance, **target_data)

        # Offers saved before targets defaulted to all products have none and
        # never apply; give them the same default when they are edited.
        if not instance.targets.exists():
            OfferTarget.objects.create(offer=instance, target_type='all_products')
                   
        return instance
