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


@pytest.mark.django_db
class TestRetailerCustomerFilteringAndSorting:
    def test_filter_by_status(self, api_client, retailer, customer):
        # Create mapping
        from retailers.models import RetailerCustomerMapping, RetailerBlacklist
        mapping = RetailerCustomerMapping.objects.create(retailer=retailer, customer=customer, current_balance=Decimal("10.00"))
        
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_customers')
        
        # Verify active status
        res = api_client.get(url, {'status': 'active'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 1
        
        # Blacklist customer
        RetailerBlacklist.objects.create(retailer=retailer, customer=customer, reason="Bad")
        
        # Verify active status excludes blacklist
        res = api_client.get(url, {'status': 'active'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 0
        
        # Verify blacklisted status includes blacklist
        res = api_client.get(url, {'status': 'blacklisted'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 1

    def test_filter_by_due_payment(self, api_client, retailer):
        from retailers.models import RetailerCustomerMapping
        from authentication.models import User
        # Create user 1 with due
        u1 = User.objects.create_user(username="due_user", password="pwd", user_type="customer")
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=u1, current_balance=Decimal("150.00"))
        
        # Create user 2 with no due
        u2 = User.objects.create_user(username="nodue_user", password="pwd", user_type="customer")
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=u2, current_balance=Decimal("0.00"))
        
        # Create user 3 with overpayment (negative balance)
        u3 = User.objects.create_user(username="overdue_user", password="pwd", user_type="customer")
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=u3, current_balance=Decimal("-50.00"))
        
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_customers')
        
        # Verify due_payment=true
        res = api_client.get(url, {'due_payment': 'true'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 1
        assert res.data['results'][0]['customer_id'] == u1.id
        
        # Verify due_payment=false (includes both u2 and u3)
        res = api_client.get(url, {'due_payment': 'false'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 2
        customer_ids = [c['customer_id'] for c in res.data['results']]
        assert u2.id in customer_ids
        assert u3.id in customer_ids

    def test_filter_by_customer_type(self, api_client, retailer):
        from retailers.models import RetailerCustomerMapping
        from authentication.models import User
        # App user
        u1 = User.objects.create_user(username="app_user", password="pwd", user_type="customer", registration_status="registered")
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=u1)
        
        # Shadow user
        u2 = User.objects.create_user(username="shadow_user", password="pwd", user_type="customer", registration_status="shadow")
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=u2)
        
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_customers')
        
        # App Users
        res = api_client.get(url, {'customer_type': 'registered'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 1
        assert res.data['results'][0]['customer_id'] == u1.id
        
        # Walk-in
        res = api_client.get(url, {'customer_type': 'shadow'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['count'] == 1
        assert res.data['results'][0]['customer_id'] == u2.id

    def test_sorting_customers(self, api_client, retailer):
        from retailers.models import RetailerCustomerMapping
        from authentication.models import User
        from orders.models import Order
        
        u1 = User.objects.create_user(username="cust1", password="pwd", user_type="customer")
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=u1)
        Order.objects.create(
            customer=u1, retailer=retailer, total_amount=Decimal("500.00"),
            subtotal=Decimal("500.00"), delivery_mode="delivery", payment_mode="cod",
            status="delivered"
        )
        
        u2 = User.objects.create_user(username="cust2", password="pwd", user_type="customer")
        RetailerCustomerMapping.objects.create(retailer=retailer, customer=u2)
        Order.objects.create(
            customer=u2, retailer=retailer, total_amount=Decimal("100.00"),
            subtotal=Decimal("100.00"), delivery_mode="delivery", payment_mode="cod",
            status="delivered"
        )
        Order.objects.create(
            customer=u2, retailer=retailer, total_amount=Decimal("100.00"),
            subtotal=Decimal("100.00"), delivery_mode="delivery", payment_mode="cod",
            status="delivered"
        )
        
        api_client.force_authenticate(user=retailer.user)
        url = reverse('get_retailer_customers')
        
        # Sort by most_orders
        res = api_client.get(url, {'sort_by': 'most_orders'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['results'][0]['customer_id'] == u2.id # 2 orders
        
        # Sort by highest_spent
        res = api_client.get(url, {'sort_by': 'highest_spent'})
        assert res.status_code == status.HTTP_200_OK
        assert res.data['results'][0]['customer_id'] == u1.id # 500 spent
