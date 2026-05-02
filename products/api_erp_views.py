from decimal import Decimal
from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.utils import timezone
from rest_framework.decorators import action, api_view, permission_classes
from django.db import transaction
from retailers.models import Supplier, RetailerProfile, RetailerCustomerMapping
from retailers.serializers import SupplierSerializer
from products.models import PurchaseInvoice, PurchaseItem, SupplierLedger, Product, ProductBatch, ProductInventoryLog
from orders.models import Order, OrderItem
from django.db.models import Sum, Q, Count, F, Case, When, DecimalField
from products.serializers import PurchaseInvoiceSerializer, SupplierLedgerSerializer
from orders.serializers import OrderDetailSerializer
from common.permissions import IsRetailerOwner
from authentication.utils import normalize_phone_number
from customers.models import CustomerProfile

class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        return Supplier.objects.filter(retailer=retailer).order_by('-id')
    
    search_fields = ['company_name', 'contact_person', 'phone_number', 'email']

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

    search_fields = ['invoice_number', 'supplier_name']

    def perform_create(self, serializer):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        invoice = serializer.save(retailer=retailer)
        
    def perform_destroy(self, instance):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        # Ensure retailer ownership
        if instance.retailer != retailer:
            raise ValidationError("You do not have permission to delete this invoice.")
        
        with transaction.atomic():
            # 1. Reverse stock
            old_items = list(instance.items.all())
            for old_item in old_items:
                product = old_item.product
                if product:
                    Product.objects.filter(id=product.id, retailer=retailer).update(
                        quantity=F('quantity') - old_item.quantity
                    )
                    product.refresh_from_db()
                    ProductInventoryLog.objects.create(
                        product=product,
                        created_by=self.request.user,
                        quantity_change=-old_item.quantity,
                        previous_quantity=product.quantity + old_item.quantity,
                        new_quantity=product.quantity,
                        log_type='removed',
                        reason=f'Purchase Invoice Deleted: #{instance.invoice_number}'
                    )
            
            # 2. Delete invoice 
            # (Ledger entries cascade implicitly, and Signal updates balance_due automatically!)
            instance.delete()


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
        retailer = RetailerProfile.objects.get(user=self.request.user)
        supplier = serializer.validated_data.get('supplier')
        if not supplier or supplier.retailer_id != retailer.id:
            raise ValidationError({'supplier': 'Invalid supplier for this retailer.'})

        with transaction.atomic():
            ledger_entry = serializer.save(supplier=supplier)
            # The signal sync_supplier_ledger_balances now handles balance_due logic mathematically.


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
        
        # Robust phone matching using normalized 10 digits
        mobile_match_id = normalize_phone_number(customer_mobile)
        
        # Also clean the full customer_mobile to remove spaces/dashes for username/phone fields
        customer_mobile = ''.join(c for c in str(customer_mobile) if c.isdigit())
        
        if mobile_match_id:
            # 1. Try last 10 digits match (standard)
            order_customer = User.objects.filter(
                Q(username__endswith=mobile_match_id) | 
                Q(phone_number__endswith=mobile_match_id)
            ).first()
            
            # 2. Try exact match if not found (extra safety)
            if not order_customer:
                order_customer = User.objects.filter(
                    Q(username=customer_mobile) | 
                    Q(phone_number=customer_mobile) |
                    Q(username='user_' + customer_mobile) # Common pattern in some systems
                ).first()
        
        if not order_customer and customer_mobile:
            # Create Shadow User for this walk-in
            import secrets
            from django.db import IntegrityError
            from django.core.exceptions import ValidationError
            try:
                # Use a clean username without prefix if possible
                username_to_use = customer_mobile
                
                with transaction.atomic():
                    order_customer = User.objects.create(
                        username=username_to_use,
                        phone_number=customer_mobile,
                        first_name=customer_name or "Walk-in",
                        registration_status='shadow',
                        is_phone_verified=False,
                        user_type='customer'
                    )
                    order_customer.set_password(secrets.token_urlsafe(12))
                    order_customer.save()
            except (IntegrityError, ValidationError):
                # If creation fails, someone with this number/username exists, find them aggressively
                order_customer = User.objects.filter(
                    Q(username__endswith=mobile_match_id) | 
                    Q(phone_number__endswith=mobile_match_id) |
                    Q(username__icontains=customer_mobile) |
                    Q(phone_number__icontains=customer_mobile)
                ).first()
            
        # Ensure Shadow/Registered User has a CustomerProfile for rating synchronization
        if order_customer:
            CustomerProfile.objects.get_or_create(user=order_customer)

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

            # Payment Breakdown Logic (Initialized to 0 to avoid NULL constraints)
            cash_amount = Decimal('0')
            upi_amount = Decimal('0')
            card_amount = Decimal('0')
            credit_amount = Decimal('0')
            
            payment_details = data.get('payment_details', {})
            if payment_details and isinstance(payment_details, dict):
                cash_amount = Decimal(str(payment_details.get('cash', 0) or 0))
                upi_amount = Decimal(str(payment_details.get('upi', 0) or 0))
                card_amount = Decimal(str(payment_details.get('card', 0) or 0))
                credit_amount = Decimal(str(payment_details.get('credit', 0) or 0))
            
            # If no payment_details provided, fallback to legacy payment_mode
            if not payment_details:
                legacy_mode = data.get('payment_mode', 'cash')
                if legacy_mode == 'cash':
                    cash_amount = rounded_total
                elif legacy_mode == 'upi':
                    upi_amount = rounded_total
                elif legacy_mode == 'card':
                    card_amount = rounded_total
                elif legacy_mode == 'credit':
                    credit_amount = rounded_total

            # Verify total matches
            sum_payments = cash_amount + upi_amount + card_amount + credit_amount
            if abs(sum_payments - rounded_total) > Decimal('0.01'):
                 # If it doesn't match perfectly, adjust cash if it's a small rounding diff, or error out
                 if abs(sum_payments - rounded_total) <= Decimal('1.00') and not payment_details:
                     # Auto-adjust for legacy
                     cash_amount = rounded_total
                 else:
                     raise ValueError(f"Total payment {sum_payments} does not match order total {rounded_total}")

            # Determine payment mode label
            payment_mode = data.get('payment_mode', 'cash')
            modes_count = sum(1 for v in [cash_amount, upi_amount, card_amount, credit_amount] if v > 0)
            if modes_count > 1:
                payment_mode = 'split'
            elif credit_amount > 0:
                payment_mode = 'credit'
            elif upi_amount > 0:
                payment_mode = 'upi'
            elif card_amount > 0:
                payment_mode = 'card'
            else:
                payment_mode = 'cash'

            order = Order.objects.create(
                customer=order_customer,
                guest_name=customer_name if not order_customer else None,
                guest_mobile=customer_mobile if not order_customer else None,
                retailer=retailer,
                source='pos',
                delivery_mode='pickup',
                payment_mode=payment_mode,
                status='delivered',
                subtotal=rounded_subtotal,
                delivery_fee=0,
                discount_amount=rounded_discount,
                total_amount=rounded_total,
                cash_amount=cash_amount,
                upi_amount=upi_amount,
                card_amount=card_amount,
                credit_amount=credit_amount,
                payment_status='verified' if payment_mode in ['cash', 'split'] else 'pending_verification',
                confirmed_at=timezone.now(),
                delivered_at=timezone.now()
            )

            # Award Loyalty Points
            order.award_loyalty_points()

            # CRM Mapping and Credit Ledger Update
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
                
                # Record Credit Transaction if any
                if credit_amount > 0:
                    # Enforce credit limit if set
                    if mapping.credit_limit > 0:
                        available_credit = mapping.credit_limit - mapping.current_balance
                        if credit_amount > available_credit:
                            # Rollback: delete the order we just created
                            order.delete()
                            raise ValueError(
                                f"Credit limit exceeded. "
                                f"Limit: ₹{mapping.credit_limit}, "
                                f"Current balance: ₹{mapping.current_balance}, "
                                f"Available: ₹{max(available_credit, 0)}"
                            )
                    
                    mapping.record_transaction(
                        transaction_type='SALE',
                        amount=credit_amount,
                        order=order,
                        notes=f"POS Udhaar for Order #{order.order_number}"
                    )
                else:
                    mapping.save()

            # Create Order Items and Reduce Inventory
            for item in items_data:
                product = Product.objects.select_for_update().get(id=item['product_id'], retailer=retailer)
                batch_id = item.get('batch_id')
                batch = None
                if batch_id:
                    batch = ProductBatch.objects.select_for_update().get(id=batch_id, product=product)
                
                qty = Decimal(str(item['quantity']))
                unit_price = Decimal(str(item['unit_price']))
                
                # Price validation: ensure frontend price matches actual price
                expected_price = Decimal(str(batch.price)) if batch else Decimal(str(product.price))
                if unit_price != expected_price:
                    raise ValueError(
                        f"Price mismatch for {product.name}: "
                        f"sent ₹{unit_price}, expected ₹{expected_price}"
                    )
                
                # Calculate previous quantity for logging
                prev_qty = batch.quantity if (batch and product.track_inventory) else product.quantity
                
                # Reduce inventory using the model method (handles FIFO if batch is None)
                # POS allows negative stock (allow_negative=True)
                if not product.reduce_quantity(qty, batch=batch, allow_negative=True):
                    raise ValueError(f"Unexpected error reducing stock for {product.name}")
                
                new_qty = batch.quantity if (batch and product.track_inventory) else product.quantity

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    batch=batch,
                    product_name=product.name,
                    product_price=batch.price if batch else product.price,
                    product_unit=product.unit,
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=qty * unit_price
                )

                if product.track_inventory:
                    # Log inventory
                    ProductInventoryLog.objects.create(
                        product=product,
                        batch=batch,
                        created_by=request.user,
                        quantity_change=-qty,
                        previous_quantity=prev_qty,
                        new_quantity=new_qty,
                        log_type='sold',
                        reason=f'POS Sale: Order #{order.order_number}'
                    )

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
    
    # Check Unified User Table using robust matching
    last_10 = normalize_phone_number(mobile_number)
    existing_user = None
    if last_10:
        existing_user = User.objects.filter(
            Q(username__endswith=last_10) | Q(phone_number__endswith=last_10)
        ).first()
    
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
        
    # Check legacy POS walk-in data
    past_order = Order.objects.filter(
        retailer=retailer,
        guest_mobile__endswith=last_10 if last_10 else 'NON_EXISTENT'
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
    if len(query) >= 10:
        # Full match: search globally across all app users
        last_10 = normalize_phone_number(query)
        online_users = User.objects.filter(
            Q(username__endswith=last_10) | Q(phone_number__endswith=last_10)
        ).exclude(is_staff=True)[:5]
    else:
        # Partial match
        online_users = User.objects.filter(
            Q(username__icontains=query) | Q(phone_number__icontains=query)
        ).exclude(is_staff=True)[:5]

    for u in online_users:
        mobile = normalize_phone_number(u.username)
        if mobile not in seen_mobiles:
            suggestions.append({
                'mobile': mobile,
                'name': u.get_full_name() or u.username,
                'status': 'verified' if u.registration_status == 'registered' else 'shadow'
            })
            seen_mobiles.add(mobile)
            
    # 2. Search Offline Guest list
    guest_orders = Order.objects.filter(
        retailer=retailer,
        guest_mobile__icontains=query
    ).exclude(guest_name__isnull=True).exclude(guest_name='').order_by('-created_at')[:30]
    
    for o in guest_orders:
        mobile = normalize_phone_number(o.guest_mobile)
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
        
    today = timezone.localtime(timezone.now()).date()
    # Filter orders for today for this retailer
    todays_orders = Order.objects.filter(
        retailer=retailer,
        created_at__date=today
    ).exclude(status='cancelled')
    
    summary = todays_orders.aggregate(
        total_sales=Sum('total_amount'),
        order_count=Count('id'),
        
        # Accurate Breakdown: use breakdown fields if populated, 
        # otherwise fall back to total_amount based on payment_mode (legacy orders)
        cash_sales=Sum(Case(
            When(cash_amount__gt=0, then=F('cash_amount')),
            When(payment_mode='cash', cash_amount=0, then=F('total_amount')),
            default=0,
            output_field=DecimalField()
        )),
        digital_sales=Sum(Case(
            When(Q(upi_amount__gt=0) | Q(card_amount__gt=0), then=F('upi_amount') + F('card_amount')),
            When(payment_mode='upi', upi_amount=0, then=F('total_amount')),
            default=0,
            output_field=DecimalField()
        )),
        credit_sales=Sum(Case(
            When(credit_amount__gt=0, then=F('credit_amount')),
            When(payment_mode='credit', credit_amount=0, then=F('total_amount')),
            default=0,
            output_field=DecimalField()
        )),
        
        # Source (POS vs Online)
        pos_sales=Sum('total_amount', filter=Q(source='pos')),
        online_sales=Sum('total_amount', filter=Q(source='app') | Q(source__isnull=True))
    )
    
    # 2. Subtract Returns
    from returns.models import SalesReturn
    today_returns = SalesReturn.objects.filter(retailer=retailer, created_at__date=today).aggregate(
        cash_returns=Sum('refund_amount', filter=Q(refund_payment_mode='cash')),
        upi_returns=Sum('refund_amount', filter=Q(refund_payment_mode='upi')),
        pos_returns=Sum('refund_amount', filter=Q(order__source='pos') | Q(order__isnull=True)),
        online_returns=Sum('refund_amount', filter=Q(order__source='app'))
    )
    
    cash_refunds = float(today_returns['cash_returns'] or 0)
    upi_refunds = float(today_returns['upi_returns'] or 0)
    pos_refunds = float(today_returns['pos_returns'] or 0)
    online_refunds = float(today_returns['online_returns'] or 0)
    
    cash_sales = float(summary['cash_sales'] or 0) - cash_refunds
    digital_sales = float(summary['digital_sales'] or 0) - upi_refunds
    total_sales = float(summary['total_sales'] or 0) - (cash_refunds + upi_refunds)
    pos_sales = float(summary['pos_sales'] or 0) - pos_refunds
    online_sales = float(summary['online_sales'] or 0) - online_refunds
    
    # Defaults and Formatting
    res = {
        'date': today,
        'total_sales': total_sales,
        'order_count': summary['order_count'] or 0,
        'cash_sales': cash_sales,
        'digital_sales': digital_sales,
        'credit_sales': float(summary['credit_sales'] or 0),
        'pos_sales': pos_sales,
        'online_sales': online_sales,
        'cash_refunds': cash_refunds,
        'upi_refunds': upi_refunds,
        'shop_name': retailer.shop_name
    }
    
    return Response(res)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def erp_dashboard_summary(request):
    try:
        retailer = RetailerProfile.objects.get(user=request.user)
    except RetailerProfile.DoesNotExist:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    suppliers = Supplier.objects.filter(retailer=retailer)
    
    total_debt = 0
    total_advance = 0
    
    for s in suppliers:
        if s.balance_due > 0:
            total_debt += s.balance_due
        elif s.balance_due < 0:
            total_advance += abs(s.balance_due)
            
    return Response({
        'total_outstanding_debt': float(total_debt),
        'total_advance_paid': float(total_advance),
        'total_suppliers': suppliers.count()
    })
