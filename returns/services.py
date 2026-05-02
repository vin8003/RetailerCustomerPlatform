from django.db import transaction
from django.utils import timezone
from products.models import Product, ProductBatch, ProductInventoryLog, SupplierLedger
from retailers.models import RetailerCustomerMapping
from .models import SalesReturn, SalesReturnItem, PurchaseReturn, PurchaseReturnItem
from django.db.models import Sum
from decimal import Decimal

def process_sales_return(retailer, order, items_data, refund_payment_mode, reason, created_by):
    """
    Atomic logic to process a sales return:
    1. Validate quantities
    2. Create SalesReturn record
    3. Loop items:
       - Update stock (+ quantity)
       - Update batch stock (+ quantity)
       - Create ProductInventoryLog
    """
    with transaction.atomic():
        sales_return = SalesReturn.objects.create(
            retailer=retailer,
            order=order,
            customer=order.customer if order else None,
            refund_payment_mode=refund_payment_mode,
            reason=reason,
            created_by=created_by
        )
        
        total_refund = 0
        for item in items_data:
            product = item['product']
            batch = item.get('batch')
            qty = item['quantity']
            unit_price = item['refund_unit_price']
            order_item = item.get('order_item')
            
            # Validation: Ensure we don't return more than purchased
            if order_item:
                already_returned = SalesReturnItem.objects.filter(order_item=order_item).aggregate(total=Sum('quantity'))['total'] or 0
                if already_returned + qty > order_item.quantity:
                    raise ValueError(f"Cannot return {qty} units of {product.name}. Already returned: {already_returned}, Purchased: {order_item.quantity}")

            # 1. Update Inventory
            product.increase_quantity(qty, batch=batch)
            
            # 2. Log Change
            ProductInventoryLog.objects.create(
                product=product,
                batch=batch,
                log_type='returned',
                quantity_change=qty,
                previous_quantity=product.quantity - qty,
                new_quantity=product.quantity,
                reason=f"Sales Return: {reason}" if reason else "Sales Return",
                created_by=created_by
            )
            
            item_total = qty * unit_price
            total_refund += item_total
            
            SalesReturnItem.objects.create(
                sales_return=sales_return,
                product=product,
                batch=batch,
                order_item=order_item,
                quantity=qty,
                refund_unit_price=unit_price,
                total_refund=item_total
            )
            
        sales_return.refund_amount = total_refund
        sales_return.save()
        
        # 3. Update CRM Mapping if order/customer exists
        if order and order.customer:
            mapping = RetailerCustomerMapping.objects.filter(
                retailer=retailer, 
                customer=order.customer
            ).first()
            if mapping:
                mapping.total_spent -= Decimal(str(total_refund))
                if mapping.total_spent < 0:
                    mapping.total_spent = 0
                
                # If the original order had credit (Udhaar), reduce the outstanding balance
                if order.credit_amount and order.credit_amount > 0:
                    # Calculate proportional credit refund
                    # If entire order was credit, refund full return amount from balance
                    # If split, refund proportional credit portion
                    if order.total_amount > 0:
                        credit_ratio = order.credit_amount / order.total_amount
                        credit_refund = (Decimal(str(total_refund)) * credit_ratio).quantize(Decimal('0.01'))
                    else:
                        credit_refund = Decimal('0.00')
                    
                    if credit_refund > 0:
                        mapping.record_transaction(
                            transaction_type='RETURN',
                            amount=credit_refund,
                            order=order,
                            notes=f"Sales Return refund for Order #{order.order_number}"
                        )
                    else:
                        mapping.save()
                else:
                    mapping.save()
        
        # 4. Update Loyalty Points if order/customer exists
        if order and order.customer and order.points_earned > 0:
            from customers.models import CustomerLoyalty, LoyaltyTransaction
            
            # Proportional points reduction
            # points_to_revert = (total_refund / subtotal) * points_earned
            revert_points = (Decimal(str(total_refund)) / order.subtotal) * order.points_earned
            revert_points = revert_points.quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
            
            if revert_points > 0:
                loyalty, _ = CustomerLoyalty.objects.get_or_create(
                    customer=order.customer,
                    retailer=retailer
                )
                loyalty.points -= revert_points
                if loyalty.points < 0:
                    loyalty.points = 0
                loyalty.save()
                
                # Update order points_earned
                order.points_earned -= revert_points
                if order.points_earned < 0:
                    order.points_earned = 0
                order.save(update_fields=['points_earned'])
                
                # Create Transaction
                LoyaltyTransaction.objects.create(
                    customer=order.customer,
                    retailer=retailer,
                    amount=revert_points,
                    transaction_type='redeem', # Reverting earned points is recorded as redemption/negative adjust
                    description=f"Points reverted due to return (Order #{order.order_number})"
                )

        return sales_return

def process_purchase_return(retailer, supplier, invoice, items_data, notes, created_by):
    """
    Atomic logic to process a purchase return:
    1. Validate quantities
    2. Create PurchaseReturn record
    3. Loop items:
       - Update stock (- quantity)
       - Update batch stock (- quantity)
       - Create ProductInventoryLog
    4. Create DEBIT entry in SupplierLedger
    """
    with transaction.atomic():
        from django.utils.timezone import now
        import random, string
        hasher = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return_number = f"RET-{now().strftime('%y%m%d')}-{hasher}"

        purchase_return = PurchaseReturn.objects.create(
            retailer=retailer,
            supplier=supplier,
            invoice=invoice,
            return_number=return_number,
            notes=notes,
            created_by=created_by
        )
        
        total_return_value = 0
        for item in items_data:
            product = item['product']
            batch = item.get('batch')
            qty = item['quantity']
            price = item['purchase_price']
            purchase_item = item.get('purchase_item')
            
            # Validation
            if purchase_item:
                already_returned = PurchaseReturnItem.objects.filter(purchase_item=purchase_item).aggregate(total=Sum('quantity'))['total'] or 0
                if already_returned + qty > purchase_item.quantity:
                    raise ValueError(f"Cannot return {qty} units of {product.name}. Already returned: {already_returned}, Purchased: {purchase_item.quantity}")

            # 1. Update Inventory (- quantity)
            product.reduce_quantity(qty, batch=batch, allow_negative=True)
            
            # 2. Log Change
            ProductInventoryLog.objects.create(
                product=product,
                batch=batch,
                log_type='removed',
                quantity_change=-qty,
                previous_quantity=product.quantity + qty,
                new_quantity=product.quantity,
                reason=f"Purchase Return to Supplier: {notes}" if notes else "Purchase Return",
                created_by=created_by
            )
            
            item_total = qty * price
            total_return_value += item_total
            
            PurchaseReturnItem.objects.create(
                purchase_return=purchase_return,
                product=product,
                batch=batch,
                purchase_item=purchase_item,
                quantity=qty,
                purchase_price=price,
                total=item_total
            )
            
        purchase_return.total_amount = total_return_value
        purchase_return.save()
        
        # 3. Update Supplier Ledger
        SupplierLedger.objects.create(
            supplier=supplier,
            date=timezone.now().date(),
            amount=total_return_value,
            transaction_type='DEBIT',
            notes=f"Purchase Return for #{invoice.invoice_number if invoice else 'Manual'}"
        )
        
        return purchase_return
