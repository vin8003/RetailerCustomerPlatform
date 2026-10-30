"""seed_e2e (OE-368): same dataset on every run, and never against a remote database."""
import json
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from offers.models import Offer
from orders.models import Order
from products.models import Product
from retailers.models import RetailerCustomerMapping, RetailerProfile


def seed():
    out = StringIO()
    call_command('seed_e2e', stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def dataset():
    shops = RetailerProfile.objects.filter(shop_name__startswith='E2E')
    return {
        'shops': sorted(shops.values_list('shop_name', flat=True)),
        'products': sorted(
            Product.objects.filter(retailer__in=shops).values_list('retailer__shop_name', 'name', 'price', 'quantity')
        ),
        'khata': sorted(
            RetailerCustomerMapping.objects.filter(retailer__in=shops).values_list(
                'retailer__shop_name', 'customer__username', 'current_balance', 'credit_limit'
            )
        ),
        'orders': Order.objects.filter(retailer__in=shops).count(),
        'offers': Offer.objects.filter(retailer__in=shops).count(),
    }


class SeedE2ETests(TestCase):
    def test_second_run_gives_the_same_dataset(self):
        first_ids = seed()
        first = dataset()
        second_ids = seed()

        self.assertEqual(dataset(), first)
        self.assertEqual(first_ids['retailers'], second_ids['retailers'])
        self.assertEqual(first_ids['customers'], second_ids['customers'])
        self.assertEqual(len(first['products']), 5)
        self.assertIn(('E2E Kirana', 'Atta 5kg', Decimal('250.00')), [p[:3] for p in first['products']])

    def test_refuses_a_remote_database_host(self):
        with mock.patch.dict(settings.DATABASES['default'], {'HOST': 'db.example.com'}):
            with self.assertRaisesMessage(CommandError, "refuses to run against database host 'db.example.com'"):
                seed()
        self.assertFalse(RetailerProfile.objects.filter(shop_name__startswith='E2E').exists())
