import pytest
from django.urls import reverse
from rest_framework import status
from authentication.models import User
from retailers.models import RetailerProfile, Supplier


def _result_ids(response):
    data = response.data["results"] if isinstance(response.data, dict) else response.data
    return [row["id"] for row in data]


def _search(api_client, user, query=None):
    api_client.force_authenticate(user=user)
    url = reverse("erp-supplier-list")
    params = {} if query is None else {"search": query}
    return api_client.get(url, params)


@pytest.mark.django_db
class TestSupplierSearch:
    @pytest.fixture
    def supplier(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="ABC Foods",
            contact_person="Ravi Kumar",
            phone_number="9876543210",
        )

    @pytest.fixture
    def other_supplier(self):
        other_user = User.objects.create_user(
            username="other_supplier_retailer",
            email="other_supplier_retailer@test.com",
            password="TestPass123!",
            user_type="retailer",
            is_active=True,
        )
        other_retailer = RetailerProfile.objects.create(
            user=other_user,
            shop_name="Other Shop",
            address_line1="456 Side St",
            city="OtherCity",
            state="OtherState",
            pincode="654321",
            is_active=True,
        )
        return Supplier.objects.create(
            retailer=other_retailer,
            company_name="ABC Other Corp",
            contact_person="Someone Else",
            phone_number="1111111111",
        )

    @pytest.fixture
    def decoy(self, retailer):
        return Supplier.objects.create(
            retailer=retailer,
            company_name="ZZZ Widgets",
            contact_person="Anita Shah",
            phone_number="1112223333",
        )

    def test_search_by_company_name_substring(self, api_client, retailer_user, supplier, decoy):
        response = _search(api_client, retailer_user, "abc")
        assert response.status_code == status.HTTP_200_OK
        assert _result_ids(response) == [supplier.id]

    def test_search_by_phone_substring(self, api_client, retailer_user, supplier, decoy):
        response = _search(api_client, retailer_user, "765")
        assert response.status_code == status.HTTP_200_OK
        assert _result_ids(response) == [supplier.id]

    def test_search_by_contact_person(self, api_client, retailer_user, supplier, decoy):
        response = _search(api_client, retailer_user, "Ravi")
        assert response.status_code == status.HTTP_200_OK
        assert _result_ids(response) == [supplier.id]

    def test_search_with_no_matches_returns_empty(self, api_client, retailer_user, supplier, decoy):
        response = _search(api_client, retailer_user, "zzzz-no-such")
        assert response.status_code == status.HTTP_200_OK
        assert _result_ids(response) == []

    def test_search_excludes_other_retailer_suppliers(
        self, api_client, retailer_user, supplier, other_supplier
    ):
        response = _search(api_client, retailer_user, "ABC")
        assert response.status_code == status.HTTP_200_OK
        ids = _result_ids(response)
        assert supplier.id in ids
        assert other_supplier.id not in ids

    def test_list_without_search_returns_200(self, api_client, retailer_user, supplier, decoy):
        response = _search(api_client, retailer_user)
        assert response.status_code == status.HTTP_200_OK
        ids = _result_ids(response)
        assert supplier.id in ids
        assert decoy.id in ids
