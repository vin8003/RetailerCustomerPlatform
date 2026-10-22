"""NUL in a query value or JSON string is a 400 before any view runs (PostgreSQL text cannot hold it)."""
import json

import pytest
from django.test import override_settings

NUL_ERROR = {"error": "Text cannot contain the NUL character (\\u0000)."}


@pytest.mark.django_db
class TestRejectNulCharacters:
    def test_query_value(self, api_client):
        resp = api_client.get("/api/retailer/", {"search": "rice\x00"})
        assert resp.status_code == 400
        assert resp.json() == NUL_ERROR

    def test_query_key(self, api_client):
        assert api_client.get("/api/retailer/?se%00arch=rice").status_code == 400

    def test_json_body(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        resp = api_client.post("/api/cart/clear/", {"retailer_id": "1\x00"}, format="json")
        assert resp.status_code == 400
        assert resp.json() == NUL_ERROR

    def test_escaped_backslash_text_is_not_a_nul(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        body = json.dumps({"retailer_id": "\\u0000"})  # the six characters \u0000, no NUL
        resp = api_client.post("/api/cart/clear/", body, content_type="application/json")
        assert resp.status_code == 404  # reaches the view: no such shop

    def test_form_bodies_are_not_read(self, api_client):
        resp = api_client.post("/api/auth/customer/login/", {"username": "a\x00", "password": "x"})
        assert resp.status_code != 404
        assert resp.json() != NUL_ERROR

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10)
    def test_body_over_the_upload_limit_is_left_to_the_view(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        resp = api_client.post("/api/cart/clear/", {"retailer_id": "1\x00"}, format="json")
        assert resp.status_code == 404

    def test_plain_requests_pass(self, api_client, retailer):
        assert api_client.get("/api/retailer/", {"search": "Products"}).status_code == 200
