from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers


def patch():
    from .serializers import OrderListSerializer
    OrderListSerializer.customer_average_rating = serializers.SerializerMethodField()

    def get_customer_average_rating(self, obj):
        try:
            if obj.customer and obj.customer.customer_profile:
                return obj.customer.customer_profile.average_rating
        except ObjectDoesNotExist:
            return None
        return None

    OrderListSerializer.get_customer_average_rating = get_customer_average_rating
