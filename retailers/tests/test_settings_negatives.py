"""Shop settings negatives: operating hours, reward configuration, profile money fields.

Each refusal re-reads the row to prove nothing was saved.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from retailers.models import RetailerOperatingHours, RetailerRewardConfig

pytestmark = pytest.mark.django_db


def put(client, user, name, body):
    client.force_authenticate(user=user)
    return client.put(reverse(name), body, format='json')


# --- operating hours ------------------------------------------------------------------------------

def test_hours_body_required(api_client, retailer_user, retailer):
    r = put(api_client, retailer_user, 'update_operating_hours', {})
    assert r.status_code == 400
    assert r.json() == {'error': 'Operating hours data is required'}


def test_closing_before_opening_is_400(api_client, retailer_user, retailer):
    r = put(api_client, retailer_user, 'update_operating_hours', {'operating_hours': [
        {'day_of_week': 'monday', 'is_open': True, 'opening_time': '18:00', 'closing_time': '09:00'}]})
    assert r.status_code == 400
    assert 'Opening time must be before closing time' in str(r.json())
    assert not RetailerOperatingHours.objects.filter(retailer=retailer, day_of_week='monday').exists()


def test_unknown_day_is_400(api_client, retailer_user, retailer):
    r = put(api_client, retailer_user, 'update_operating_hours', {'operating_hours': [
        {'day_of_week': 'funday', 'is_open': True, 'opening_time': '09:00', 'closing_time': '18:00'}]})
    assert r.status_code == 400
    assert 'day_of_week' in r.json()
    assert RetailerOperatingHours.objects.filter(retailer=retailer).count() == 0


def test_bad_time_format_is_400(api_client, retailer_user, retailer):
    r = put(api_client, retailer_user, 'update_operating_hours', {'operating_hours': [
        {'day_of_week': 'monday', 'is_open': True, 'opening_time': '25:99', 'closing_time': '18:00'}]})
    assert r.status_code == 400
    assert 'opening_time' in r.json()


# OE-402: a non-list body 500s. Repro: PUT /api/retailer/operating-hours/ {"operating_hours": "mon"}
# -> 500 ('str' object has no attribute 'get'). Expect 400.
@pytest.mark.xfail(strict=True, reason='OE-402: non-list operating_hours gives 500')
def test_non_list_hours_is_400(api_client, retailer_user, retailer):
    r = put(api_client, retailer_user, 'update_operating_hours', {'operating_hours': 'mon'})
    assert r.status_code == 400


# OE-403: a batch with one bad day is not atomic; earlier days are saved before the 400.
# Repro: PUT {"operating_hours": [{monday 09:00-18:00}, {tuesday 18:00-09:00}]} -> 400 but monday
# row exists. Expect nothing saved.
@pytest.mark.xfail(strict=True, reason='OE-403: operating hours batch is not atomic')
def test_bad_day_in_batch_saves_nothing(api_client, retailer_user, retailer):
    r = put(api_client, retailer_user, 'update_operating_hours', {'operating_hours': [
        {'day_of_week': 'monday', 'is_open': True, 'opening_time': '09:00', 'closing_time': '18:00'},
        {'day_of_week': 'tuesday', 'is_open': True, 'opening_time': '18:00', 'closing_time': '09:00'}]})
    assert r.status_code == 400
    assert RetailerOperatingHours.objects.filter(retailer=retailer).count() == 0


def test_customer_cannot_edit_hours(api_client, customer, retailer):
    r = put(api_client, customer, 'update_operating_hours', {'operating_hours': [{'day_of_week': 'monday'}]})
    assert r.status_code == 403


# --- reward configuration -------------------------------------------------------------------------

def reward(client, user, **body):
    return put(client, user, 'manage_reward_configuration', body)


# OE-404: reward settings accept out-of-range values and save them. Repro: PUT
# /api/retailer/reward-config/ {"conversion_rate": "-1"} (or max_reward_usage_percent 150 / -5,
# cashback_percentage -2) -> 200 and the value is stored. Expect 400 and no change.
@pytest.mark.xfail(strict=True, reason='OE-404: reward config accepts negative / >100% values')
@pytest.mark.parametrize('field, value', [
    ('conversion_rate', '-1'),
    ('max_reward_usage_percent', '150'),
    ('max_reward_usage_percent', '-5'),
    ('cashback_percentage', '-2'),
])
def test_reward_config_out_of_range(api_client, retailer_user, retailer, field, value):
    reward(api_client, retailer_user)  # creates the default config
    before = getattr(RetailerRewardConfig.objects.get(retailer=retailer), field)
    r = reward(api_client, retailer_user, **{field: value})
    assert r.status_code == 400, r.content
    assert getattr(RetailerRewardConfig.objects.get(retailer=retailer), field) == before


def test_reward_config_garbage_number(api_client, retailer_user, retailer):
    r = reward(api_client, retailer_user, conversion_rate='abc')
    assert r.status_code == 400
    assert 'conversion_rate' in r.json()


# --- profile money fields -------------------------------------------------------------------------

@pytest.mark.parametrize('field', ['delivery_charge', 'minimum_order_amount', 'free_delivery_threshold'])
def test_negative_profile_money_is_refused(api_client, retailer_user, retailer, field):
    before = getattr(retailer, field)
    api_client.force_authenticate(user=retailer_user)
    r = api_client.put(reverse('update_retailer_profile'), {field: '-10'}, format='json')
    if r.status_code == 405:
        r = api_client.patch(reverse('update_retailer_profile'), {field: '-10'}, format='json')
    assert r.status_code == 400, r.content
    retailer.refresh_from_db()
    assert getattr(retailer, field) == before


def test_negative_delivery_radius_is_refused(api_client, retailer_user, retailer):
    before = retailer.delivery_radius
    api_client.force_authenticate(user=retailer_user)
    r = api_client.put(reverse('update_retailer_profile'), {'delivery_radius': -3}, format='json')
    if r.status_code == 405:
        r = api_client.patch(reverse('update_retailer_profile'), {'delivery_radius': -3}, format='json')
    assert r.status_code == 400, r.content
    retailer.refresh_from_db()
    assert retailer.delivery_radius == before
