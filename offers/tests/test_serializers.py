import pytest
from rest_framework.test import APIRequestFactory
from offers.serializers import OfferSerializer
from offers.models import Offer, OfferTarget

@pytest.mark.django_db
class TestOfferSerializer:
    
    def test_create_offer_with_targets(self, retailer_user, retailer, category):
        factory = APIRequestFactory()
        request = factory.post('/')
        request.user = retailer_user
        
        data = {
            "name": "Category Sale",
            "offer_type": "percentage",
            "value": "20.00",
            "targets": [
                {
                    "target_type": "category",
                    "category": category.id,
                    "is_excluded": False
                }
            ]
        }
        
        serializer = OfferSerializer(data=data, context={'request': request})
        assert serializer.is_valid()
        offer = serializer.save()
        
        assert offer.retailer == retailer
        assert offer.targets.count() == 1
        assert offer.targets.first().category == category

    def test_create_offer_without_targets_defaults_to_all_products(self, retailer_user, retailer):
        factory = APIRequestFactory()
        request = factory.post('/')
        request.user = retailer_user

        data = {
            "name": "Rs 50 off on 499+",
            "offer_type": "cart_value",
            "value_type": "amount",
            "value": "50.00",
            "min_order_value": "499.00",
        }

        serializer = OfferSerializer(data=data, context={'request': request})
        assert serializer.is_valid(), serializer.errors
        offer = serializer.save()

        assert offer.targets.count() == 1
        target = offer.targets.first()
        assert target.target_type == "all_products"
        assert target.is_excluded is False

    def test_update_offer_without_targets_gets_all_products(self, retailer_user, retailer):
        offer = Offer.objects.create(retailer=retailer, name="Old offer", offer_type="cart_value", value_type="amount", value="50.00")
        assert offer.targets.count() == 0

        factory = APIRequestFactory()
        request = factory.patch('/')
        request.user = retailer_user

        serializer = OfferSerializer(offer, data={"min_order_value": "499.00"}, partial=True, context={'request': request})
        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()

        assert list(updated.targets.values_list('target_type', flat=True)) == ["all_products"]

    def test_update_offer_replace_targets(self, retailer_user, retailer, product):
        factory = APIRequestFactory()
        request = factory.put('/')
        request.user = retailer_user
        
        offer = Offer.objects.create(
            retailer=retailer, name="Old Offer", offer_type="flat_amount", value=10
        )
        OfferTarget.objects.create(offer=offer, target_type="all_products")
        
        data = {
            "name": "Updated Offer",
            "offer_type": "flat_amount",
            "value": "15.00",
            "targets": [
                {
                    "target_type": "product",
                    "product": product.id,
                    "is_excluded": False
                }
            ]
        }
        
        serializer = OfferSerializer(offer, data=data, context={'request': request})
        assert serializer.is_valid()
        updated_offer = serializer.save()
        
        assert updated_offer.name == "Updated Offer"
        assert updated_offer.targets.count() == 1
        assert updated_offer.targets.first().target_type == "product"
        assert updated_offer.targets.first().product == product
