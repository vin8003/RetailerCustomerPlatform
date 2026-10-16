from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from cart.models import CartItem
from offers.models import Offer, OfferTarget


@pytest.mark.django_db
def test_cart_summary_exposes_tax_after_offers(
    api_client, customer, retailer, cart, product
):
    product.price = Decimal('118.00')
    product.gst_rate = Decimal('18.00')
    product.save(update_fields=['price', 'gst_rate'])
    offer = Offer.objects.create(
        retailer=retailer,
        name='Online 10% Off',
        offer_type='percentage',
        value=Decimal('10.00'),
        applicable_on='mobile',
        is_active=True,
    )
    OfferTarget.objects.create(
        offer=offer,
        target_type='product',
        product=product,
    )
    CartItem.objects.create(
        cart=cart,
        product=product,
        quantity=1,
        unit_price=product.price,
    )
    api_client.force_authenticate(user=customer)

    response = api_client.get(
        reverse('get_cart_summary'),
        {'retailer_id': retailer.id},
    )

    assert response.status_code == status.HTTP_200_OK
    assert Decimal(response.data['total_amount']) == Decimal('106.20')
    assert Decimal(response.data['taxable_amount']) == Decimal('90.00')
    assert Decimal(response.data['tax_amount']) == Decimal('16.20')
