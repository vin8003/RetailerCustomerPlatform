from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Prefetch, Q, Sum
from .models import SalesReturn, PurchaseReturn, SalesReturnItem, PurchaseReturnItem
from .serializers import SalesReturnSerializer, PurchaseReturnSerializer
from .services import process_sales_return, process_purchase_return
from retailers.models import RetailerProfile, Supplier
from orders.models import Order, OrderItem
from products.models import PurchaseInvoice, Product, ProductBatch, PurchaseItem
from common.client_input import error_message, id_value, list_of_objects, money_value, quantity_value


SALES_RETURN_NOTES_MAX = 1000


def _shop_for(user):
    """The caller's shop profile; 404 (not 500) for customers and profile-less staff."""
    return get_object_or_404(RetailerProfile, user=user)


# Returns are posted once through the services, which move stock and refunds. A generic
# edit or delete would skip that (and could point a return at another shop's order).
RETURN_HTTP_METHODS = ['get', 'post', 'head', 'options']


def _return_lines(items_data, price_field, link_field):
    """
    Parse return lines. Lines without a product, quantity or price are skipped as before
    (the return screens only send the rows being returned). A negative quantity or price
    would move stock and money the wrong way, and a return with no lines is empty, so
    both are a 400.
    """
    lines = []
    for item in list_of_objects(items_data, 'items'):
        product_id = item.get('product_id')
        qty = item.get('quantity')
        price = item.get(price_field)
        if not product_id or not qty or price is None:
            continue
        lines.append({
            'product_id': id_value(product_id, 'product_id'),
            'batch_id': id_value(item['batch_id'], 'batch_id') if item.get('batch_id') else None,
            'link_id': id_value(item[link_field], link_field) if item.get(link_field) else None,
            'quantity': quantity_value(qty, 'quantity'),
            'price': money_value(price, price_field),
        })
    if not lines:
        raise ValidationError({'items': [f'Each item needs product_id, quantity and {price_field}.']})
    return lines


class SalesReturnViewSet(viewsets.ModelViewSet):
    serializer_class = SalesReturnSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = RETURN_HTTP_METHODS

    def get_queryset(self):
        retailer = _shop_for(self.request.user)
        return SalesReturn.objects.filter(retailer=retailer).prefetch_related(
            Prefetch(
                'items',
                queryset=SalesReturnItem.objects.select_related('product', 'batch'),
            )
        )

    @action(detail=False, methods=['get'])
    def search_order(self, request):
        retailer = _shop_for(request.user)
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
        orders = list(orders)
        
        if not orders:
            return Response({'error': 'No matching orders found'}, status=404)

        returned_by_item = dict(
            SalesReturnItem.objects.filter(order_item__order__in=orders)
            .values('order_item_id')
            .annotate(total=Sum('quantity'))
            .values_list('order_item_id', 'total')
        )
            
        results = []
        for order in orders:
            items_data = []
            for item in order.items.all():
                # Calculate how much already returned for this specific row
                returned_qty = returned_by_item.get(item.id) or 0
                items_data.append({
                    'id': item.id,
                    'product_id': item.product.id,
                    'product_name': item.product.name,
                    'quantity': item.quantity,
                    'already_returned': returned_qty,
                    'available_qty': max(0, item.quantity - returned_qty),
                    'unit_price': item.unit_price,
                    'batch_id': item.batch_id,
                    'unit': item.product.unit,
                    'hsn_code': item.hsn_code,
                    'gst_rate': item.gst_rate,
                    'product_gst_rate': item.product.gst_rate,
                    'tax_type': item.tax_type,
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
        retailer = _shop_for(request.user)
        order_id = request.data.get('order_id')
        items_data = request.data.get('items', [])
        payment_mode = request.data.get('refund_payment_mode', 'cash')
        reason = request.data.get('reason', '')
        notes = request.data.get('notes') or ''
        if not isinstance(notes, str):
            return Response({'error': 'notes must be text'}, status=status.HTTP_400_BAD_REQUEST)
        notes = notes.strip()
        if len(notes) > SALES_RETURN_NOTES_MAX:
            return Response(
                {'error': f'notes must be at most {SALES_RETURN_NOTES_MAX} characters'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not items_data:
            return Response({'error': 'No items provided for return'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lines = _return_lines(items_data, 'refund_unit_price', 'order_item_id')
            if order_id:
                order_id = id_value(order_id, 'order_id')
        except ValidationError as exc:
            return Response({'error': error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

        order = None
        if order_id:
            order = get_object_or_404(Order, id=order_id, retailer=retailer)

        # Prepare items data with actual product/batch/order_item objects
        processed_items = []
        for line in lines:
            product = get_object_or_404(Product, id=line['product_id'], retailer=retailer)
            batch = None
            if line['batch_id']:
                batch = get_object_or_404(ProductBatch, id=line['batch_id'], product=product)

            order_item = None
            if line['link_id']:
                order_item = get_object_or_404(OrderItem, id=line['link_id'], order=order)

            processed_items.append({
                'product': product,
                'batch': batch,
                'order_item': order_item,
                'quantity': line['quantity'],
                'refund_unit_price': line['price'],
            })

        try:
            sales_return = process_sales_return(
                retailer=retailer,
                order=order,
                items_data=processed_items,
                refund_payment_mode=payment_mode,
                reason=reason,
                notes=notes,
                created_by=request.user
            )
            serializer = self.get_serializer(sales_return)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PurchaseReturnViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseReturnSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = RETURN_HTTP_METHODS

    def get_queryset(self):
        retailer = _shop_for(self.request.user)
        return PurchaseReturn.objects.filter(retailer=retailer)

    @action(detail=False, methods=['get'])
    def get_invoice_items(self, request):
        retailer = _shop_for(request.user)
        invoice_id = request.query_params.get('invoice_id')
        if not invoice_id:
            return Response({'error': 'invoice_id is required'}, status=400)
        try:
            invoice_id = id_value(invoice_id, 'invoice_id')
        except ValidationError as exc:
            return Response({'error': error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

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
                'hsn_code': item.hsn_code,
                'gst_rate': item.gst_rate,
                'product_gst_rate': item.product.gst_rate if item.product else None,
                'tax_type': item.tax_type,
            })
            
        return Response(items_data)

    def create(self, request, *args, **kwargs):
        retailer = _shop_for(request.user)
        supplier_id = request.data.get('supplier_id')
        invoice_id = request.data.get('invoice_id')
        items_data = request.data.get('items', [])
        notes = request.data.get('notes', '')

        if not items_data:
            return Response({'error': 'No items provided for return'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lines = _return_lines(items_data, 'purchase_price', 'purchase_item_id')
            supplier_id = id_value(supplier_id, 'supplier_id')
            if invoice_id:
                invoice_id = id_value(invoice_id, 'invoice_id')
        except ValidationError as exc:
            return Response({'error': error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

        supplier = get_object_or_404(Supplier, id=supplier_id, retailer=retailer)
        invoice = None
        if invoice_id:
            invoice = get_object_or_404(PurchaseInvoice, id=invoice_id, retailer=retailer)

        # Prepare items data
        processed_items = []
        for line in lines:
            product = get_object_or_404(Product, id=line['product_id'], retailer=retailer)
            batch = None
            if line['batch_id']:
                batch = get_object_or_404(ProductBatch, id=line['batch_id'], product=product)

            purchase_item = None
            if line['link_id']:
                purchase_item = get_object_or_404(PurchaseItem, id=line['link_id'], invoice=invoice)

            processed_items.append({
                'product': product,
                'batch': batch,
                'purchase_item': purchase_item,
                'quantity': line['quantity'],
                'purchase_price': line['price'],
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
