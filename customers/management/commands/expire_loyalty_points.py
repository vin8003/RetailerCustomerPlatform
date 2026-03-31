from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from customers.models import CustomerLoyalty, LoyaltyTransaction

class Command(BaseCommand):
    help = 'Expires loyalty points older than 90 days (FIFO Logic)'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # 1. Get all earn transactions that have passed their expiry date but are not marked as processed
        expired_txs = LoyaltyTransaction.objects.filter(
            transaction_type='earn',
            expiry_date__lt=now,
            is_expired=False
        ).select_related('customer', 'retailer')
        
        if not expired_txs.exists():
            self.stdout.write(self.style.SUCCESS('No points to expire today.'))
            return

        # Group by customer and retailer to handle updates efficiently
        expiries = {}
        for tx in expired_txs:
            key = (tx.customer_id, tx.retailer_id)
            if key not in expiries:
                expiries[key] = {'total_points_to_expire': 0, 'tx_ids': []}
            expiries[key]['total_points_to_expire'] += tx.amount
            expiries[key]['tx_ids'].append(tx.id)

        count = 0
        for (cust_id, ret_id), data in expiries.items():
            with transaction.atomic():
                try:
                    loyalty = CustomerLoyalty.objects.get(customer_id=cust_id, retailer_id=ret_id)
                    
                    # We only subtract what's actually left in the balance.
                    # If points were already spent, the balance will be lower than the original earn amount.
                    amount_actually_expiring = min(loyalty.points, data['total_points_to_expire'])
                    
                    if amount_actually_expiring > 0:
                        loyalty.points -= amount_actually_expiring
                        loyalty.save()
                        
                        # Log the expiry for clarity in history
                        LoyaltyTransaction.objects.create(
                            customer_id=cust_id,
                            retailer_id=ret_id,
                            amount=amount_actually_expiring,
                            transaction_type='expire',
                            description=f"Points expired (3-month validity over)"
                        )
                    
                    # Mark original earn transactions as expired so we don't count them again next time
                    LoyaltyTransaction.objects.filter(id__in=data['tx_ids']).update(is_expired=True)
                    count += 1
                except CustomerLoyalty.DoesNotExist:
                    # If balance record is gone, just mark transactions as expired
                    LoyaltyTransaction.objects.filter(id__in=data['tx_ids']).update(is_expired=True)

        self.stdout.write(self.style.SUCCESS(f'Successfully processed expiries for {count} customer loyalty accounts.'))
