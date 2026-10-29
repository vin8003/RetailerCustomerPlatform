"""Slice data for the scan / delivery-fee / bundle e2e specs (seed_e2e calls ``seed_sfb``).

Own shop, customer and products, all prefixed SFB / sfb_, read from
e2e/seed/scan_fee_bundles.json. The shop name does not start with "E2E", so the
core dataset checks (test_seed_e2e) are unaffected. Also runnable on its own:
``python manage.py seed_e2e_sfb`` (local / CI databases only).
"""
import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from cart.models import Cart
from customers.models import CustomerAddress, CustomerProfile
from offers.models import Offer
from orders.models import Order
from products.models import Product

SFB_DATA = json.loads((Path(settings.BASE_DIR) / 'e2e' / 'seed' / 'scan_fee_bundles.json').read_text())


def seed_sfb(cmd, password):
    """Reset the SFB shop to the same state. ``cmd`` is the seed_e2e Command (upsert helpers)."""
    r, c, delivery = SFB_DATA['retailer'], SFB_DATA['customer'], SFB_DATA['delivery']
    shop = cmd.upsert_shop(cmd.upsert_user(r['username'], r['shop_name'], r['phone'], 'retailer', password),
                           r['shop_name'], r['phone'])
    # Own pin, apart from the core shop. Addresses sit due north (same longitude), so the
    # distance depends only on the latitude offset and the fee distances stay exact.
    shop_lat, shop_lng = Decimal(r['latitude']), Decimal(r['longitude'])
    shop.latitude, shop.longitude = shop_lat, shop_lng
    shop.delivery_fee_mode = 'distance'
    shop.delivery_fee_tiers = delivery['tiers']
    shop.delivery_fee_per_km = Decimal(delivery['per_km'])
    shop.delivery_radius = Decimal(delivery['radius_km'])
    shop.free_delivery_threshold = Decimal(delivery['free_delivery_threshold'])
    shop.save(update_fields=['latitude', 'longitude', 'delivery_fee_mode', 'delivery_fee_tiers', 'delivery_fee_per_km',
                             'delivery_radius', 'free_delivery_threshold'])

    customer = cmd.upsert_user(c['username'], c['first_name'], c['phone'], 'customer', password)
    CustomerProfile.objects.get_or_create(user=customer)

    Order.objects.filter(retailer=shop).delete()
    Order.objects.filter(customer=customer).delete()
    Cart.objects.filter(customer=customer).delete()
    Offer.objects.filter(retailer=shop).delete()
    Product.objects.filter(retailer=shop, parent_bulk_product__isnull=False).delete()
    Product.objects.filter(retailer=shop).delete()
    CustomerAddress.objects.filter(customer=customer).delete()

    addresses = {}
    for i, (key, a) in enumerate(SFB_DATA['addresses'].items()):
        addresses[key] = CustomerAddress.objects.create(
            customer=customer, title=f'SFB {key}', address_type='other', address_line1=a['line1'],
            city='New Delhi', state='Delhi', pincode='110001',
            latitude=shop_lat + Decimal(a['lat_offset']), longitude=shop_lng,
            is_default=(i == 0),
        ).id

    products = {}
    for key, p in SFB_DATA['products'].items():
        fields = dict(retailer=shop, name=p['name'], barcode=p['barcode'], price=Decimal(p['price']),
                      gst_rate=Decimal('0.00'), unit='piece', is_active=True, is_available=True,
                      track_inventory=True)
        if p.get('bundle_of'):
            # A bundle sells N units of its base product and draws stock from it (KAN-13 pack sizing).
            parent = products[p['bundle_of']]
            product = Product.objects.create(**fields, quantity=Decimal('0'), parent_bulk_product=parent,
                                             conversion_factor=Decimal(p['units']))
        else:
            product = Product.objects.create(**fields, quantity=Decimal(p['stock']))
        products[key] = product
    return {
        'retailer': shop.id,
        'customer': customer.id,
        'addresses': addresses,
        'products': {key: p.id for key, p in products.items()},
    }


class Command(BaseCommand):
    help = 'Reset only the SFB slice e2e data (also run by seed_e2e). Local/CI databases only.'

    def handle(self, *args, **options):
        import os
        from retailers.management.commands.seed_e2e import DEFAULT_PASSWORD, Command as SeedE2E, assert_local_database

        assert_local_database()
        with transaction.atomic():
            ids = seed_sfb(SeedE2E(), os.getenv('E2E_PASSWORD', DEFAULT_PASSWORD))
        self.stdout.write(json.dumps({'sfb': ids}, sort_keys=True))
