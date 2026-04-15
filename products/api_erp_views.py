from decimal import Decimal
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.utils import timezone
from rest_framework.decorators import action, api_view, permission_classes
from django.db import transaction
from rest_framework.decorators import action
from retailers.models import Supplier, RetailerProfile, RetailerCustomerMapping
from retailers.serializers import SupplierSerializer
from products.models import PurchaseInvoice, PurchaseItem, SupplierLedger, Product, ProductInventoryLog
from orders.models import Order, OrderItem
from django.db.models import Sum, Q, Count, F
from django.db import transaction
from products.serializers import PurchaseInvoiceSerializer, SupplierLedgerSerializer
from orders.models import Order, OrderItem
from orders.serializers import OrderDetailSerializer
from common.permissions import IsRetailerOwner

class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        return Supplier.objects.filter(retailer=retailer)

    def perform_create(self, serializer):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        serializer.save(retailer=retailer)


class PurchaseInvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseInvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        qs = PurchaseInvoice.objects.filter(retailer=retailer).order_by('-invoice_date')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            qs = qs.filter(invoice_date__gte=start_date)
        if end_date:
            qs = qs.filter(invoice_date__lte=end_date)
        return qs

    def perform_create(self, serializer):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        invoice = serializer.save(retailer=retailer)


class SupplierLedgerViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierLedgerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        qs = SupplierLedger.objects.filter(supplier__retailer=retailer)
        supplier_id = self.request.query_params.get('supplier')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if supplier_id:
            qs = qs.filter(supplier__id=supplier_id)
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            ledger_entry = serializer.save()
            
            # Use atomic F() expressions to prevent stale in-memory balance issues
            # CREDIT (Stock Received) increases balance_due
            # DEBIT (Payment Made) decreases balance_due
            if ledger_entry.transaction_type == 'CREDIT':
                Supplier.objects.filter(id=ledger_entry.supplier.id).update(
                    balance_due=F('balance_due') + ledger_entry.amount
                )
            elif ledger_entry.transaction_type == 'DEBIT':
                Supplier.objects.filter(id=ledger_entry.supplier.id).update(
                    balance_due=F('balance_due') - ledger_entry.amount
                )


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_pos_order(request):
    """
    Create an order directly from the POS interface.
    Accepts: {
        'items': [{'product_id': 1, 'quantity': 2, 'unit_price': 100}],
        'payment_mode': 'cash' | 'upi',
        'subtotal': 200,
        'discount_amount': 0,
        'total_amount': 200
    }
    """
    try:
        retailer = RetailerProfile.objects.get(user=request.user)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Only retailers can use POS.'}, status=status.HTTP_403_FORBIDDEN)

    data = request.data
    items_data = data.get('items', [])
    if not items_data:
        return Response({'error': 'Cart is empty.'}, status=status.HTTP_400_BAD_REQUEST)

    customer_name = data.get('customer_name', '').strip()
    customer_mobile = data.get('customer_mobile', '').strip()
    
    order_customer = None
    if customer_mobile:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        # Robust phone matching: strip formatting and match last 10 digits
        clean_mobile = ''.join(filter(str.isdigit, customer_mobile))
        last_10 = clean_mobile[-10:] if len(clean_mobile) >= 10 else clean_mobile
        
        if last_10:
            user_query = (
                User.objects.filter(username__endswith=last_10) | 
                User.objects.filter(phone_number__endswith=last_10)
            )
            order_customer = user_query.first()
        
        if not order_customer and customer_mobile:
            # Create Shadow User for this walk-in
            import secrets
            order_customer = User.objects.create(
                username=customer_mobile,
                phone_number=customer_mobile,
                first_name=customer_name or "Walk-in",
                registration_status='shadow',
                is_phone_verified=False
            )
            order_customer.set_password(secrets.token_urlsafe(12))
            order_customer.save()

    try:
        from retailers.models import RetailerCustomerMapping
        with transaction.atomic():
            # Round amounts to nearest whole rupee as requested
            raw_subtotal = Decimal(str(data.get('subtotal', 0)))
            raw_discount = Decimal(str(data.get('discount_amount', 0)))
            raw_total = Decimal(str(data.get('total_amount', 0)))

            rounded_subtotal = raw_subtotal.quantize(Decimal('1'), rounding='ROUND_HALF_UP')
            rounded_discount = raw_discount.quantize(Decimal('1'), rounding='ROUND_HALF_UP')
            rounded_total = raw_total.quantize(Decimal('1'), rounding='ROUND_HALF_UP')

            order = Order.objects.create(
                customer=order_customer,
                # We no longer strictly need guest_name/mobile since it's in the User object, 
                # but keeping for backward compatibility in the model for now.
                guest_name=customer_name if not order_customer else None,
                guest_mobile=customer_mobile if not order_customer else None,
                retailer=retailer,
                source='pos',
                delivery_mode='pickup',
                payment_mode=data.get('payment_mode', 'cash'),
                status='delivered',
                subtotal=rounded_subtotal,
                delivery_fee=0,
                discount_amount=rounded_discount,
                total_amount=rounded_total,
                payment_status='verified' if data.get('payment_mode') == 'cash' else 'pending_verification',
                confirmed_at=timezone.now(),
                delivered_at=timezone.now()
            )

            # Award Loyalty Points
            order.award_loyalty_points()

            # CRM Mapping Update
            if order_customer:
                mapping, created = RetailerCustomerMapping.objects.get_or_create(
                    retailer=retailer,
                    customer=order_customer
                )
                if customer_name and not mapping.nickname:
                    mapping.nickname = customer_name
                
                mapping.total_orders += 1
                mapping.total_spent += rounded_total
                mapping.last_order_date = timezone.now()
                mapping.save()

            # Create Order Items and Reduce Inventory
            for item in items_data:
                product = Product.objects.select_for_update().get(id=item['product_id'], retailer=retailer)
                qty = int(item['quantity'])
                unit_price = float(item['unit_price'])
                
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name=product.name,
                    product_price=product.price,
                    product_unit=product.unit,
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=qty * unit_price
                )

                if product.track_inventory:
                    if product.quantity >= qty:
                        product.quantity -= qty
                        product.save()
                        
                        # Log inventory
                        ProductInventoryLog.objects.create(
                            product=product,
                            created_by=request.user,
                            quantity_change=-qty,
                            previous_quantity=product.quantity + qty,
                            new_quantity=product.quantity,
                            log_type='sold',
                            reason=f'POS Sale: Order #{order.order_number}'
                        )
                    else:
                        raise ValueError(f"Not enough stock for {product.name}")

        response_data = {
            'message': 'POS Order created successfully!',
            'order': OrderDetailSerializer(order, context={'request': request}).data
        }
        return Response(response_data, status=status.HTTP_201_CREATED)

    except ValueError as ve:
        return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def verify_pos_customer(request):
    try:
        retailer = RetailerProfile.objects.get(user=request.user)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    mobile_number = request.GET.get('mobile_number', '').strip()
    if not mobile_number:
        return Response({'status': 'new'})
        
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    # Check Unified User Table
    clean_mobile = mobile_number.replace('+91', '')
    user_query = User.objects.filter(username=mobile_number) | User.objects.filter(phone_number=mobile_number) | User.objects.filter(username=f"+91{clean_mobile}")
    existing_user = user_query.first()
    
    if existing_user:
        name = existing_user.get_full_name() or existing_user.username
        status_label = 'verified' if existing_user.registration_status == 'registered' else 'shadow'
        
        # Check for custom Retailer nickname
        from retailers.models import RetailerCustomerMapping
        mapping = RetailerCustomerMapping.objects.filter(retailer=retailer, customer=existing_user).first()
        if mapping and mapping.nickname:
            name = mapping.nickname

        return Response({
            'status': status_label,
            'name': name,
            'is_app_user': existing_user.registration_status == 'registered'
        })
        
    # Check legacy POS walk-in data (to be migrated)
    past_order = Order.objects.filter(
        retailer=retailer,
        guest_mobile=mobile_number
    ).exclude(guest_name__isnull=True).exclude(guest_name='').order_by('-created_at').first()
    
    if past_order and past_order.guest_name:
        return Response({
            'status': 'returning_guest',
            'name': past_order.guest_name
        })
        
    return Response({'status': 'new'})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_pos_customers(request):
    try:
        retailer = RetailerProfile.objects.get(user=request.user)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    query = request.GET.get('q', '').strip()
    if len(query) < 3:
        return Response([])
        
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    suggestions = []
    seen_mobiles = set()
    
    # 1. Search Online list
    if len(query) == 10:
        # Full match: search globally across all app users
        clean_mobile = query.replace('+91', '')
        user_query = User.objects.filter(username=query) | User.objects.filter(username=f"+91{clean_mobile}")
        online_users = user_query.exclude(is_staff=True)[:5]
    else:
        # Partial match: strictly search only users who have ordered from this specific retailer
        my_app_customer_ids = Order.objects.filter(retailer=retailer, customer__isnull=False).values_list('customer_id', flat=True).distinct()
        online_users = User.objects.filter(id__in=my_app_customer_ids, username__icontains=query).exclude(is_staff=True)[:5]
    for u in online_users:
        mobile = u.username.replace('+91', '')
        if mobile not in seen_mobiles:
            suggestions.append({
                'mobile': mobile,
                'name': u.get_full_name() or u.username,
                'status': 'verified'
            })
            seen_mobiles.add(mobile)
            
    # 2. Search Offline Guest list
    guest_orders = Order.objects.filter(
        retailer=retailer,
        guest_mobile__icontains=query
    ).exclude(guest_name__isnull=True).exclude(guest_name='').order_by('-created_at')[:30]
    
    for o in guest_orders:
        mobile = o.guest_mobile
        if mobile and mobile not in seen_mobiles:
            suggestions.append({
                'mobile': mobile,
                'name': o.guest_name,
                'status': 'returning_guest'
            })
            seen_mobiles.add(mobile)
            if len(suggestions) >= 8:
                break
                
    return Response(suggestions)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_inventory_ledger(request):
    try:
        retailer = RetailerProfile.objects.get(user=request.user)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    product_id = request.GET.get('product_id')
    if not product_id:
        return Response({'error': 'product_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        product = Product.objects.get(id=product_id, retailer=retailer)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
        
    logs = ProductInventoryLog.objects.filter(product=product).order_by('-created_at')[:100]
    
    data = []
    for log in logs:
        data.append({
            'id': log.id,
            'log_type': log.log_type,
            'quantity_change': log.quantity_change,
            'previous_quantity': log.previous_quantity,
            'new_quantity': log.new_quantity,
            'reason': log.reason,
            'created_at': log.created_at,
            'created_by': log.created_by.get_full_name() if log.created_by else 'System'
        })
        
    return Response(data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_daily_sales_summary(request):
    try:
        retailer = RetailerProfile.objects.get(user=request.user)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    today = timezone.now().date()
    # Filter orders for today for this retailer
    todays_orders = Order.objects.filter(
        retailer=retailer,
        created_at__date=today
    ).exclude(status='cancelled')
    
    # Aggregations
    summary = todays_orders.aggregate(
        total_sales=Sum('total_amount'),
        order_count=Count('id'),
        
        # Cash vs Digital
        cash_sales=Sum('total_amount', filter=Q(payment_mode='cash') | Q(payment_mode='cash_pickup')),
        digital_sales=Sum('total_amount', filter=Q(payment_mode='upi') | Q(payment_mode='online') | Q(payment_mode='card')),
        
        # Source (POS vs Online)
        pos_sales=Sum('total_amount', filter=Q(source='pos')),
        online_sales=Sum('total_amount', filter=Q(source='app') | Q(source__isnull=True))
    )
    
    # Defaults and Formatting
    res = {
        'date': today,
        'total_sales': float(summary['total_sales'] or 0),
        'order_count': summary['order_count'] or 0,
        'cash_sales': float(summary['cash_sales'] or 0),
        'digital_sales': float(summary['digital_sales'] or 0),
        'pos_sales': float(summary['pos_sales'] or 0),
        'online_sales': float(summary['online_sales'] or 0),
        'shop_name': retailer.shop_name
    }
    
    return Response(res)
