from rest_framework import permissions


class IsRetailerUser(permissions.BasePermission):
    """
    Custom permission to only allow retailer users
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.user_type == 'retailer'
        )


class IsCustomerUser(permissions.BasePermission):
    """
    Custom permission to only allow customer users
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.user_type == 'customer'
        )


class IsRetailerOwner(permissions.BasePermission):
    """
    Custom permission to only allow retailer owners to access their own data
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.user_type == 'retailer'
        )
    
    def has_object_permission(self, request, view, obj):
        # Check if the object has a retailer field
        if hasattr(obj, 'retailer'):
            return obj.retailer.user == request.user
        # Check if the object has a user field and is retailer profile
        elif hasattr(obj, 'user') and hasattr(obj, 'shop_name'):
            return obj.user == request.user
        return False


class IsCustomerOwner(permissions.BasePermission):
    """
    Custom permission to only allow customers to access their own data
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.user_type == 'customer'
        )
    
    def has_object_permission(self, request, view, obj):
        # Check if the object has a customer field
        if hasattr(obj, 'customer'):
            return obj.customer == request.user
        # Check if the object has a user field and is customer profile
        elif hasattr(obj, 'user') and not hasattr(obj, 'shop_name'):
            return obj.user == request.user
        return False


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners to edit their objects
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions for any request
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write permissions only to the owner
        if hasattr(obj, 'user'):
            return obj.user == request.user
        elif hasattr(obj, 'customer'):
            return obj.customer == request.user
        elif hasattr(obj, 'retailer'):
            return obj.retailer.user == request.user
        
        return False


class IsRetailerOrCustomerOwner(permissions.BasePermission):
    """
    Custom permission for objects that can be accessed by either retailer or customer owners
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.user_type in ['retailer', 'customer']
        )
    
    def has_object_permission(self, request, view, obj):
        # For orders, both customer and retailer can access
        if hasattr(obj, 'customer') and hasattr(obj, 'retailer'):
            return (
                obj.customer == request.user or 
                obj.retailer.user == request.user
            )
        
        # For other objects, check ownership
        if hasattr(obj, 'customer'):
            return obj.customer == request.user
        elif hasattr(obj, 'retailer'):
            return obj.retailer.user == request.user
        elif hasattr(obj, 'user'):
            return obj.user == request.user
        
        return False


class IsAuthenticatedOrReadOnly(permissions.BasePermission):
    """
    Custom permission to allow read-only access to unauthenticated users
    and full access to authenticated users
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated


class IsVerifiedUser(permissions.BasePermission):
    """
    Custom permission to only allow verified users
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_phone_verified
        )


class IsActiveRetailer(permissions.BasePermission):
    """
    Custom permission to only allow active retailers
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.user_type == 'retailer'):
            return False
        
        try:
            from retailers.models import RetailerProfile
            retailer = RetailerProfile.objects.get(user=request.user)
            return retailer.is_active
        except RetailerProfile.DoesNotExist:
            return False


class CanManageOrders(permissions.BasePermission):
    """
    Custom permission for order management
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.user_type in ['retailer', 'customer']
        )
    
    def has_object_permission(self, request, view, obj):
        # Customers can only view their own orders
        if request.user.user_type == 'customer':
            return obj.customer == request.user
        
        # Retailers can manage orders for their shop
        elif request.user.user_type == 'retailer':
            return obj.retailer.user == request.user
        
        return False


class CanUpdateOrderStatus(permissions.BasePermission):
    """
    Custom permission for updating order status - only retailers
    """
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.user_type == 'retailer'
        )
    
    def has_object_permission(self, request, view, obj):
        return obj.retailer.user == request.user
