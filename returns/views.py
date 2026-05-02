from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Q, Sum
from decimal import Decimal
from .models import SalesReturn, PurchaseReturn, SalesReturnItem, PurchaseReturnItem
from .serializers import SalesReturnSerializer, PurchaseReturnSerializer
from .services import process_sales_return, process_purchase_return
from retailers.models import RetailerProfile, Supplier
from orders.models import Order, OrderItem
from products.models import PurchaseInvoice, Product, ProductBatch, PurchaseItem

class SalesReturnViewSet(viewsets.ModelViewSet):
    serializer_class = SalesReturnSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        return SalesReturn.objects.filter(retailer=retailer)

    @action(detail=False, methods=['get'])
    def search_order(self, request):
        retailer = RetailerProfile.objects.get(user=request.user)
        query = request.query_params.get('query')
        if not query:
            return Response({'error': 'Query parameter is required'}, status=400)
            
        # Comprehensive Search: Number, Mobile (Guest/Customer), Name (Guest/Customer)
        orders = Order.objects.filter(
            Q(order_number__icontains=query) | 
            Q(guest_mobile__icontains=query) |
            Q(customer__phone_number__icontains=query) |
            Q(guest_name__icontains=query) |
            Q(customer__first_name__icontains=query) |
            Q(customer__last_name__icontains=query),
            retailer=retailer,
            status='delivered'
        ).prefetch_related('items__product').order_by('-created_at')[:20] # Limit to 20 results
        
        if not orders.exists():
            return Response({'error': 'No matching orders found'}, status=404)
            
        results = []
        for order in orders:
            items_data = []
            for item in order.items.all():
                # Calculate how much already returned for this specific row
                returned_qty = SalesReturnItem.objects.filter(order_item=item).aggregate(total=Sum('quantity'))['total'] or 0
                items_data.append({
                    'id': item.id,
                    'product_id': item.product.id,
                    'product_name': item.product.name,
                    'quantity': item.quantity,
                    'already_returned': returned_qty,
                    'available_qty': max(0, item.quantity - returned_qty),
                    'unit_price': item.unit_price,
                    'batch_id': item.batch_id,
                })

            results.append({
                'id': order.id,
                'order_number': order.order_number,
                'customer_name': order.guest_name or (order.customer.get_full_name() if order.customer else (order.customer.username if order.customer else "Walk-in")),
                'customer_mobile': order.guest_mobile or (order.customer.phone_number if order.customer else ""),
                'total_amount': order.total_amount,
                'payment_mode': order.payment_mode,
                'status': order.status,
                'created_at': order.created_at,
                'items': items_data
            })
            
        return Response(results)

    def create(self, request, *args, **kwargs):
        retailer = RetailerProfile.objects.get(user=request.user)
        order_id = request.data.get('order_id')
        items_data = request.data.get('items', [])
        payment_mode = request.data.get('refund_payment_mode', 'cash')
        reason = request.data.get('reason', '')

        if not items_data:
            return Response({'error': 'No items provided for return'}, status=status.HTTP_400_BAD_REQUEST)

        order = None
        if order_id:
            order = get_object_or_404(Order, id=order_id, retailer=retailer)

        # Prepare items data with actual product/batch/order_item objects
        processed_items = []
        for item in items_data:
            product_id = item.get('product_id')
            batch_id = item.get('batch_id')
            order_item_id = item.get('order_item_id')
            qty = item.get('quantity')
            price = item.get('refund_unit_price')

            if not product_id or not qty or price is None:
                continue

            product = get_object_or_404(Product, id=product_id, retailer=retailer)
            batch = None
            if batch_id:
                batch = get_object_or_404(ProductBatch, id=batch_id, product=product)

            order_item = None
            if order_item_id:
                order_item = get_object_or_404(OrderItem, id=order_item_id, order=order)

            processed_items.append({
                'product': product,
                'batch': batch,
                'order_item': order_item,
                'quantity': Decimal(str(qty)),
                'refund_unit_price': Decimal(str(price))
            })

        try:
            sales_return = process_sales_return(
                retailer=retailer,
                order=order,
                items_data=processed_items,
                refund_payment_mode=payment_mode,
                reason=reason,
                created_by=request.user
            )
            serializer = self.get_serializer(sales_return)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PurchaseReturnViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseReturnSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        retailer = RetailerProfile.objects.get(user=self.request.user)
        return PurchaseReturn.objects.filter(retailer=retailer)

    @action(detail=False, methods=['get'])
    def get_invoice_items(self, request):
        retailer = RetailerProfile.objects.get(user=request.user)
        invoice_id = request.query_params.get('invoice_id')
        if not invoice_id:
            return Response({'error': 'invoice_id is required'}, status=400)
            
        invoice = get_object_or_404(PurchaseInvoice, id=invoice_id, retailer=retailer)
        
        items_data = []
        for item in invoice.items.all():
            returned_qty = PurchaseReturnItem.objects.filter(purchase_item=item).aggregate(total=Sum('quantity'))['total'] or 0
            items_data.append({
                'id': item.id,
                'product_id': item.product.id if item.product else None,
                'product_name': item.product.name if item.product else "Unknown Product",
                'quantity': item.quantity,
                'already_returned': returned_qty,
                'available_qty': max(0, item.quantity - returned_qty),
                'purchase_price': item.purchase_price,
                'batch_id': item.batch_id if hasattr(item, 'batch_id') else None,
            })
            
        return Response(items_data)

    def create(self, request, *args, **kwargs):
        retailer = RetailerProfile.objects.get(user=request.user)
        supplier_id = request.data.get('supplier_id')
        invoice_id = request.data.get('invoice_id')
        items_data = request.data.get('items', [])
        notes = request.data.get('notes', '')

        if not items_data:
            return Response({'error': 'No items provided for return'}, status=status.HTTP_400_BAD_REQUEST)

        supplier = get_object_or_404(Supplier, id=supplier_id, retailer=retailer)
        invoice = None
        if invoice_id:
            invoice = get_object_or_404(PurchaseInvoice, id=invoice_id, retailer=retailer)

        # Prepare items data
        processed_items = []
        for item in items_data:
            product_id = item.get('product_id')
            batch_id = item.get('batch_id')
            purchase_item_id = item.get('purchase_item_id')
            qty = item.get('quantity')
            price = item.get('purchase_price')

            if not product_id or not qty or price is None:
                continue

            product = get_object_or_404(Product, id=product_id, retailer=retailer)
            batch = None
            if batch_id:
                batch = get_object_or_404(ProductBatch, id=batch_id, product=product)

            purchase_item = None
            if purchase_item_id:
                purchase_item = get_object_or_404(PurchaseItem, id=purchase_item_id, invoice=invoice)

            processed_items.append({
                'product': product,
                'batch': batch,
                'purchase_item': purchase_item,
                'quantity': Decimal(str(qty)),
                'purchase_price': Decimal(str(price))
            })

        try:
            purchase_return = process_purchase_return(
                retailer=retailer,
                supplier=supplier,
                invoice=invoice,
                items_data=processed_items,
                notes=notes,
                created_by=request.user
            )
            serializer = self.get_serializer(purchase_return)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
