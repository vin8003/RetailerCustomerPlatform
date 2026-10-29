"""Deterministic dataset for the Playwright e2e suite (OE-368).

Every run resets the E2E shops to the same state: the E2E users are kept,
everything they own or touched (orders, carts, khata, products, offers) is
deleted and recreated with fixed values. Prints the ids the specs need as JSON.

Refuses to run unless the database host is local or a CI service container.
"""
import json
import os
from pathlib import Path
from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from authentication.models import EmailOTPVerification, OTPVerification, User
from cart.models import Cart
from customers.models import CustomerAddress, CustomerProfile
from offers.models import Offer
from orders.models import Order
from products.models import Product
from retailers.models import RetailerCustomerMapping, RetailerOperatingHours, RetailerProfile
from retailers.organization import ensure_organization_for_profile

ALLOWED_DB_HOSTS = {'localhost', '127.0.0.1', '::1', 'postgres'}

# Names, phones, barcodes, prices and khata live in e2e/seed-data.json, shared with the specs.
SEED_DATA = json.loads((Path(settings.BASE_DIR) / 'e2e' / 'seed-data.json').read_text())
DEFAULT_PASSWORD = SEED_DATA['password']

SHOP_LATITUDE = Decimal('28.61390000')
SHOP_LONGITUDE = Decimal('77.20900000')

RETAILERS = [(key, r['username'], r['shop_name'], r['phone']) for key, r in SEED_DATA['retailers'].items()]
CUSTOMERS = [(key, c['username'], c['first_name'], c['phone']) for key, c in SEED_DATA['customers'].items()]
PRODUCTS = [(key, p['name'], p['barcode'], Decimal(p['price'])) for key, p in SEED_DATA['products'].items()]
KHATA = [
    (k['customer'], k['retailer'], Decimal(k['credit_limit']), Decimal(k['balance'])) for k in SEED_DATA['khata']
]
PRODUCT_STOCK = Decimal('100')

# Phase 2 auth journeys (OE-368 follow-up).
ADMIN = SEED_DATA['admin']
PENDING = SEED_DATA['pending_retailer']
SIGNUP_RETAILER = SEED_DATA['signup']['retailer']
SIGNUP_CUSTOMER = SEED_DATA['signup']['customer']


DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
# SL1: every day 10:00-12:00 IST, so "next day 10:00-12:00" always exists.
SLOT_OPENING = time(10, 0)
SLOT_CLOSING = time(12, 0)
SLOT_CAPACITY = 10


def assert_local_database():
    host = (settings.DATABASES['default'].get('HOST') or 'localhost').strip()
    if host not in ALLOWED_DB_HOSTS and not host.startswith('/'):
        raise CommandError(f'seed_e2e refuses to run against database host {host!r}')


class Command(BaseCommand):
    help = 'Reset the deterministic e2e dataset (OE-368). Local/CI databases only.'

    def handle(self, *args, **options):
        assert_local_database()
        password = os.getenv('E2E_PASSWORD', DEFAULT_PASSWORD)
        with transaction.atomic():
            ids = self.seed(password)
        self.stdout.write(json.dumps(ids, sort_keys=True))

    def seed(self, password):
        self.reset_auth_accounts()
        retailers = {}
        for key, username, shop_name, phone in RETAILERS:
            user = self.upsert_user(username, shop_name, phone, 'retailer', password)
            retailers[key] = self.upsert_shop(user, shop_name, phone)

        customers = {}
        for key, username, first_name, phone in CUSTOMERS:
            customers[key] = self.upsert_user(username, first_name, phone, 'customer', password)
            CustomerProfile.objects.get_or_create(user=customers[key])

        shops = list(retailers.values())
        Order.objects.filter(retailer__in=shops).delete()
        Order.objects.filter(customer__in=customers.values()).delete()
        Cart.objects.filter(customer__in=customers.values()).delete()
        RetailerCustomerMapping.objects.filter(retailer__in=shops).delete()
        RetailerCustomerMapping.objects.filter(customer__in=customers.values()).delete()
        Offer.objects.filter(retailer__in=shops).delete()
        Product.objects.filter(retailer__in=shops).delete()
        CustomerAddress.objects.filter(customer__in=customers.values()).delete()

        products = {}
        for key, name, barcode, price in PRODUCTS:
            products[key] = Product.objects.create(
                retailer=retailers['R1'],
                name=name,
                barcode=barcode,
                price=price,
                quantity=PRODUCT_STOCK,
                gst_rate=Decimal('0.00'),
                unit='piece',
                is_active=True,
                is_available=True,
            )

        for customer_key, retailer_key, credit_limit, balance in KHATA:
            RetailerCustomerMapping.objects.create(
                retailer=retailers[retailer_key],
                customer=customers[customer_key],
                nickname=customers[customer_key].first_name,
                credit_limit=credit_limit,
                current_balance=balance,
            )

        address = CustomerAddress.objects.create(
            customer=customers['C2'],
            title='Home',
            address_type='home',
            address_line1='1 E2E Lane',
            city='New Delhi',
            state='Delhi',
            pincode='110001',
            latitude=SHOP_LATITUDE,
            longitude=SHOP_LONGITUDE,
            is_default=True,
        )

        admin = self.upsert_user(ADMIN['username'], ADMIN['shop_name'], ADMIN['phone'], 'retailer', password)
        admin.is_staff = True
        admin.save(update_fields=['is_staff'])
        admin_shop = self.upsert_shop(admin, ADMIN['shop_name'], ADMIN['phone'])
        # Hidden from customers: the admin shop exists only so the dashboard has a profile to load.
        RetailerProfile.objects.filter(pk=admin_shop.pk).update(is_active=False)

        pending = self.upsert_user(PENDING['username'], PENDING['shop_name'], PENDING['phone'], 'retailer', password)
        pending_shop = self.upsert_shop(pending, PENDING['shop_name'], PENDING['phone'])
        RetailerProfile.objects.filter(pk=pending_shop.pk).update(
            verification_status='pending', is_verified=False, is_active=False, rejection_reason=None,
        )

        return {
            'admin_shop': admin_shop.id,
            'pending_shop': pending_shop.id,
            'retailers': {key: shop.id for key, shop in retailers.items()},
            'customers': {key: user.id for key, user in customers.items()},
            'products': {key: product.id for key, product in products.items()},
            'c2_address': address.id,
        }

    def reset_auth_accounts(self):
        """Free the signup journeys' username/email/phone for the next run, and drop E2E users' pending OTPs.

        Signup-created accounts are retired rather than deleted: their organization is PROTECT-referenced.
        """
        signup_users = User.objects.filter(
            Q(username__in=[SIGNUP_RETAILER['username'], SIGNUP_CUSTOMER['phone'][-10:]])
            | Q(email__in=[SIGNUP_RETAILER['email'], SIGNUP_CUSTOMER['email']])
            | Q(phone_number__in=[SIGNUP_RETAILER['phone'], SIGNUP_CUSTOMER['phone']])
        )
        for user in signup_users:
            RetailerProfile.objects.filter(user=user).update(is_active=False, contact_phone='')
            user.username = f'e2e_retired_{user.pk}'
            user.email = f'e2e_retired_{user.pk}@e2e.invalid'
            user.phone_number = None
            user.is_active = False
            user.save(update_fields=['username', 'email', 'phone_number', 'is_active'])
        e2e_users = User.objects.filter(email__endswith='@e2e.invalid')
        OTPVerification.objects.filter(user__in=e2e_users).delete()
        EmailOTPVerification.objects.filter(user__in=e2e_users).delete()

    def upsert_user(self, username, first_name, phone, user_type, password):
        user, _created = User.objects.update_or_create(
            username=username,
            defaults={
                'first_name': first_name,
                'last_name': '',
                'email': f'{username}@e2e.invalid',
                'phone_number': phone,
                'user_type': user_type,
                'is_active': True,
                'is_phone_verified': True,
                'is_email_verified': True,
            },
        )
        user.set_password(password)
        user.save(update_fields=['password'])
        return user

    def upsert_shop(self, user, shop_name, phone):
        shop, _created = RetailerProfile.objects.update_or_create(
            user=user,
            defaults={
                'shop_name': shop_name,
                'contact_phone': phone,
                'address_line1': '1 E2E Market',
                'city': 'New Delhi',
                'state': 'Delhi',
                'pincode': '110001',
                'latitude': SHOP_LATITUDE,
                'longitude': SHOP_LONGITUDE,
                'offers_delivery': True,
                'offers_pickup': True,
                'accepts_cod': True,
                'accepts_upi': True,
                'upi_id': 'e2e@upi',
                'delivery_radius': 10,
                'serviceable_pincodes': [],
                'minimum_order_amount': Decimal('0.00'),
                'delivery_charge': Decimal('0.00'),
                'free_delivery_threshold': Decimal('0.00'),
                'delivery_fee_mode': 'distance',
                'delivery_fee_tiers': [{'up_to_km': '5.00', 'fee': '0.00'}, {'up_to_km': '10.00', 'fee': '0.00'}],
                'delivery_fee_per_km': Decimal('0.00'),
                'fulfillment_slot_capacity': SLOT_CAPACITY,
                'verification_status': 'approved',
                'is_verified': True,
                'is_active': True,
                'timezone': 'Asia/Kolkata',
            },
        )
        ensure_organization_for_profile(shop)
        for day in DAYS:
            RetailerOperatingHours.objects.update_or_create(
                retailer=shop,
                day_of_week=day,
                defaults={'is_open': True, 'opening_time': SLOT_OPENING, 'closing_time': SLOT_CLOSING},
            )
        return shop
