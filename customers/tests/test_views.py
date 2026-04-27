import pytest
from django.urls import reverse
from rest_framework import status
from decimal import Decimal
from customers.models import CustomerAddress, CustomerWishlist, CustomerReferral
from orders.models import Order


@pytest.mark.django_db
class TestCustomerProfileViews:
    def test_get_profile(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        url = reverse('get_customer_profile')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['username'] == customer.username

    def test_update_profile(self, api_client, customer):
        api_client.force_authenticate(user=customer)
        url = reverse('update_customer_profile')
        data = {"gender": "male", "preferred_language": "hi"}
        response = api_client.patch(url, data)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['gender'] == 'male'


@pytest.mark.django_db
class TestCustomerAddressViews:
    def test_crud_addresses(self, api_client, customer, address):
        api_client.force_authenticate(user=customer)
        
        # List
        url = reverse('get_customer_addresses')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        
        # Create
        url_create = reverse('create_customer_address')
        data = {
            "title": "Office",
            "address_line1": "789 Work St",
            "city": "WorkCity",
            "state": "WorkState",
            "pincode": "654321",
            "is_default": True
        }
        response = api_client.post(url_create, data)
        assert response.status_code == status.HTTP_201_CREATED
        
        # Verify default swap
        address.refresh_from_db()
        assert address.is_default is False
        
        # Delete (Soft)
        address_id = response.data['id']
        url_delete = reverse('delete_customer_address', kwargs={'address_id': address_id})
        response = api_client.delete(url_delete)
        assert response.status_code == status.HTTP_200_OK
        
        addr_obj = CustomerAddress.objects.get(id=address_id)
        assert addr_obj.is_active is False


@pytest.mark.django_db
class TestCustomerWishlistViews:
    def test_add_wishlist_duplicate(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        url_add = reverse('add_to_wishlist')
        api_client.post(url_add, {"product": product.id})
        
        # Duplicate Add
        response = api_client.post(url_add, {"product": product.id})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_remove_wishlist(self, api_client, customer, product):
        api_client.force_authenticate(user=customer)
        CustomerWishlist.objects.create(customer=customer, product=product)
        
        url_remove = reverse('remove_from_wishlist', kwargs={'product_id': product.id})
        response = api_client.delete(url_remove)
        assert response.status_code == status.HTTP_200_OK
        assert not CustomerWishlist.objects.filter(customer=customer, product=product).exists()


@pytest.mark.django_db
class TestCustomerDashboardView:
    def test_dashboard_stats(self, api_client, customer, retailer, address):
        api_client.force_authenticate(user=customer)
        Order.objects.create(
            customer=customer, retailer=retailer, total_amount=Decimal("500.00"),
            subtotal=Decimal("500.00"), delivery_mode="delivery", payment_mode="upi",
            status="delivered", delivery_address=address, payment_status="verified"
        )
        
        url = reverse('get_customer_dashboard')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['total_orders'] == 1
        assert float(response.data['total_spent']) == 500.00


@pytest.mark.django_db
class TestCustomerReferralView:
    def test_apply_referral_success(self, api_client, customer, retailer, reward_config):
        # Create a referrer with a profile
        from authentication.models import User
        from customers.models import CustomerProfile
        referrer_user = User.objects.create_user(username="referrer_new", email="refn@t.com", password="P")
        referrer_profile = CustomerProfile.objects.create(user=referrer_user)
        ref_code = referrer_profile.referral_code
        
        # Enable referral
        reward_config.is_referral_enabled = True
        reward_config.save()
        
        api_client.force_authenticate(user=customer)
        url = reverse('apply_referral_code')
        data = {"referral_code": ref_code, "retailer_id": retailer.id}
        
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert CustomerReferral.objects.filter(referee=customer, referrer=referrer_user).exists()

    def test_apply_referral_self_fail(self, api_client, customer, retailer, reward_config):
        ref_code = customer.customer_profile.referral_code
        reward_config.is_referral_enabled = True
        reward_config.save()
        
        api_client.force_authenticate(user=customer)
        url = reverse('apply_referral_code')
        data = {"referral_code": ref_code, "retailer_id": retailer.id}
        
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "self" in response.data['error'].lower()

    def test_apply_referral_existing_order_fail(self, api_client, customer, retailer, address, reward_config):
        # Create a valid referrer first
        from authentication.models import User
        from customers.models import CustomerProfile
        referrer_user = User.objects.create_user(username="referrer_ex", email="refex@t.com", password="P")
        referrer_profile = CustomerProfile.objects.create(user=referrer_user)
        ref_code = referrer_profile.referral_code

        # Place an order for the referee
        Order.objects.create(
            customer=customer, retailer=retailer, total_amount=Decimal("100.00"),
            subtotal=Decimal("100.00"), delivery_mode="delivery", payment_mode="upi"
        )
        
        reward_config.is_referral_enabled = True
        reward_config.save()
        
        api_client.force_authenticate(user=customer)
        url = reverse('apply_referral_code')
        data = {"referral_code": ref_code, "retailer_id": retailer.id}
        
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "first order" in response.data['error'].lower()
