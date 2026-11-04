"""Khata (customer credit ledger) negatives: bad amounts, other retailers' customers, roles."""
from decimal import Decimal

import pytest
from django.urls import reverse

from authentication.models import User
from customers.models import CustomerProfile
from retailers.models import RetailerCustomerMapping, RetailerProfile

PAY = 'record_customer_payment'


def make_retailer(username):
    owner = User.objects.create_user(username=username, email=f'{username}@t.com', password='TestPass123!',
                                     user_type='retailer', is_active=True)
    return RetailerProfile.objects.create(user=owner, shop_name=username, address_line1='1 St', city='C',
                                          state='S', pincode='123456', is_active=True, is_verified=True,
                                          verification_status='approved')


@pytest.fixture
def shop():
    return make_retailer('khata_shop')


@pytest.fixture
def buyer():
    user = User.objects.create_user(username='khata_buyer', email='kb@t.com', password='TestPass123!',
                                    user_type='customer', is_active=True)
    CustomerProfile.objects.create(user=user)
    return user


@pytest.fixture
def mapping(shop, buyer):
    return RetailerCustomerMapping.objects.create(retailer=shop, customer=buyer, credit_limit=Decimal('5000'),
                                                  current_balance=Decimal('500'))


def pay(client, user, **data):
    client.force_authenticate(user=user)
    return client.post(reverse(PAY), data, format='json')


def balance(mapping):
    mapping.refresh_from_db()
    return mapping.current_balance


@pytest.mark.django_db
class TestRecordPaymentRefusals:
    @pytest.mark.parametrize('amount', ['0', '-10', 0, -0.01])
    def test_zero_or_negative_amount(self, api_client, shop, buyer, mapping, amount):
        r = pay(api_client, shop.user, customer_id=buyer.id, amount=amount)
        assert r.status_code == 400
        # 0 is falsy, so it is caught by the "required" check before the sign check.
        assert r.json()['error'] in ('Amount must be positive', 'Customer ID and amount are required')
        assert balance(mapping) == Decimal('500')

    @pytest.mark.parametrize('amount', ['abc', '12,5', '1e', 'NaN'])
    def test_non_numeric_amount(self, api_client, shop, buyer, mapping, amount):
        r = pay(api_client, shop.user, customer_id=buyer.id, amount=amount)
        assert r.status_code == 400
        assert r.json() == {'error': 'Invalid amount'}
        assert balance(mapping) == Decimal('500')

    def test_missing_fields(self, api_client, shop, buyer, mapping):
        assert pay(api_client, shop.user, amount='10').json() == {'error': 'Customer ID and amount are required'}
        assert pay(api_client, shop.user, customer_id=buyer.id).json() == {'error': 'Customer ID and amount are required'}

    def test_customer_cannot_record(self, api_client, buyer, mapping):
        r = pay(api_client, buyer, customer_id=buyer.id, amount='10')
        assert r.status_code == 403
        assert r.json() == {'error': 'Only retailers can record payments'}
        assert balance(mapping) == Decimal('500')

    def test_unauthenticated(self, api_client, buyer, mapping):
        assert api_client.post(reverse(PAY), {'customer_id': buyer.id, 'amount': '10'}, format='json').status_code == 401

    @pytest.mark.xfail(strict=True, reason='OE-394: Http404 is swallowed by the generic except -> 500')
    def test_other_retailers_customer_is_404(self, api_client, buyer, mapping):
        other = make_retailer('khata_other')
        r = pay(api_client, other.user, customer_id=buyer.id, amount='10')
        assert r.status_code == 404

    def test_other_retailers_customer_never_changes_balance(self, api_client, buyer, mapping):
        other = make_retailer('khata_other2')
        r = pay(api_client, other.user, customer_id=buyer.id, amount='10')
        assert r.status_code >= 400
        assert balance(mapping) == Decimal('500')
        assert not RetailerCustomerMapping.objects.filter(retailer=other, customer=buyer).exists()

    def test_overpayment_beyond_balance(self, api_client, shop, buyer, mapping):
        """Paying more than owed is accepted and leaves an advance (negative balance); pin that behaviour."""
        r = pay(api_client, shop.user, customer_id=buyer.id, amount='800')
        assert r.status_code == 201
        assert balance(mapping) == Decimal('-300')


@pytest.mark.django_db
class TestLedgerAndLimitRefusals:
    def test_other_retailer_cannot_read_ledger(self, api_client, buyer, mapping):
        other = make_retailer('khata_reader')
        api_client.force_authenticate(user=other.user)
        assert api_client.get(reverse('get_customer_ledger', args=[buyer.id])).status_code == 404

    def test_customer_cannot_read_ledger(self, api_client, buyer, mapping):
        api_client.force_authenticate(user=buyer)
        r = api_client.get(reverse('get_customer_ledger', args=[buyer.id]))
        assert r.status_code == 403

    @pytest.mark.parametrize('limit, error', [('-1', 'Credit limit cannot be negative'), ('abc', 'Invalid credit limit'),
                                              ('NaN', 'Invalid credit limit'), ('Infinity', 'Invalid credit limit')])
    def test_bad_credit_limit(self, api_client, shop, buyer, mapping, limit, error):
        api_client.force_authenticate(user=shop.user)
        r = api_client.patch(reverse('update_customer_credit_limit', args=[buyer.id]), {'credit_limit': limit}, format='json')
        assert r.status_code == 400
        assert r.json() == {'error': error}
        mapping.refresh_from_db()
        assert mapping.credit_limit == Decimal('5000')

    def test_credit_limit_needs_a_field(self, api_client, shop, buyer, mapping):
        api_client.force_authenticate(user=shop.user)
        r = api_client.patch(reverse('update_customer_credit_limit', args=[buyer.id]), {}, format='json')
        assert r.status_code == 400
        assert r.json() == {'error': 'Credit limit or credit due days is required'}

    def test_customer_cannot_change_limit(self, api_client, buyer, mapping):
        api_client.force_authenticate(user=buyer)
        r = api_client.patch(reverse('update_customer_credit_limit', args=[buyer.id]), {'credit_limit': '9'}, format='json')
        assert r.status_code == 403

    def test_other_retailer_cannot_change_limit(self, api_client, buyer, mapping):
        other = make_retailer('khata_limit')
        api_client.force_authenticate(user=other.user)
        r = api_client.patch(reverse('update_customer_credit_limit', args=[buyer.id]), {'credit_limit': '1'}, format='json')
        assert r.status_code in (403, 404)
        mapping.refresh_from_db()
        assert mapping.credit_limit == Decimal('5000')
