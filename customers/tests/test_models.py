import pytest
from customers.models import (
    CustomerProfile, CustomerAddress, CustomerWishlist, 
    CustomerNotification, CustomerLoyalty, LoyaltyTransaction,
    CustomerReferral, CustomerSearchHistory
)
from django.core.exceptions import ValidationError


@pytest.mark.django_db
class TestCustomerProfile:
    def test_referral_code_generated(self, customer):
        profile = customer.customer_profile
        assert profile.referral_code.startswith("REF")
        assert len(profile.referral_code) > 5

    def test_str(self, customer):
        profile = customer.customer_profile
        assert str(profile) == f"{customer.username} - Customer Profile"


@pytest.mark.django_db
class TestCustomerAddress:
    def test_default_address_switch(self, customer, address):
        assert address.is_default is True
        
        # Create another default address
        address2 = CustomerAddress.objects.create(
            customer=customer,
            title="Office",
            address_line1="789 Work St",
            city="WorkCity",
            state="WorkState",
            pincode="654321",
            is_default=True
        )
        
        address.refresh_from_db()
        assert address.is_default is False
        assert address2.is_default is True

    def test_full_address_property(self, address):
        assert "456 Oak Lane" in address.full_address
        assert "TestCity" in address.full_address
        assert "123456" in address.full_address

    def test_str(self, address):
        assert str(address) == f"Home - {address.customer.username}"


@pytest.mark.django_db
class TestCustomerWishlist:
    def test_str(self, wishlist_item):
        assert f"{wishlist_item.customer.username}" in str(wishlist_item)
        assert f"{wishlist_item.product.name}" in str(wishlist_item)


@pytest.mark.django_db
class TestCustomerNotification:
    def test_str(self, notification):
        assert "Test Title" in str(notification)


@pytest.mark.django_db
class TestLoyaltyModels:
    def test_loyalty_str(self, customer, retailer):
        from customers.models import CustomerLoyalty
        loyalty = CustomerLoyalty.objects.create(
            customer=customer,
            retailer=retailer,
            points=100
        )
        assert "100" in str(loyalty)

    def test_transaction_str(self, customer, retailer):
        tx = LoyaltyTransaction.objects.create(
            customer=customer,
            retailer=retailer,
            amount=50,
            transaction_type="earn",
            description="Purchase"
        )
        assert "50" in str(tx)
        assert "earn" in str(tx)


@pytest.mark.django_db
class TestCustomerReferral:
    def test_str(self, customer, retailer_user, retailer):
        from authentication.models import User
        referee = User.objects.create_user(username="referee", email="r@t.com", password="P")
        referral = CustomerReferral.objects.create(
            referrer=customer,
            retailer=retailer,
            referee=referee
        )
        assert customer.username in str(referral)
        assert referee.username in str(referral)


@pytest.mark.django_db
class TestSearchHistory:
    def test_str(self, customer):
        h = CustomerSearchHistory.objects.create(
            customer=customer,
            query="milk",
            results_count=10
        )
        assert "milk" in str(h)
